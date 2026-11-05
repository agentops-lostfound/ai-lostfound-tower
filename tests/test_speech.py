import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from speech.transcriber import SpeechConfig, KoreanTranscriber


class SpeechTests(unittest.TestCase):
    def test_cached_vocabulary_txt_or_json_does_not_trigger_download(self):
        for vocab in ('vocabulary.txt', 'vocabulary.json'):
            with self.subTest(vocabulary=vocab), tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp)/'small';folder.mkdir()
                for name in ('model.bin','config.json','tokenizer.json',vocab):
                    (folder/name).write_bytes(b'test')
                download=Mock(side_effect=AssertionError('Unexpected download'))
                modules={'faster_whisper':SimpleNamespace(WhisperModel=Mock()),
                         'faster_whisper.utils':SimpleNamespace(download_model=download),
                         'ctranslate2':SimpleNamespace()}
                worker=KoreanTranscriber.__new__(KoreanTranscriber)
                worker.config=SpeechConfig(model='small',device='cpu',compute_type='int8',cache_dir=Path(tmp),offline=True)
                with patch.dict('sys.modules',modules):
                    worker._load()
                download.assert_not_called()

    def test_explicit_cpu_configuration(self):
        with self.assertRaises(ValueError):
            SpeechConfig(device='cpu').validate()
        SpeechConfig(model='small',device='cpu',compute_type='int8').validate()
        with self.assertRaises(ValueError):
            SpeechConfig(model='small.en').validate()

    def make_transcriber(self, segments):
        stt=KoreanTranscriber.__new__(KoreanTranscriber)
        stt.config=SpeechConfig(device='cpu',compute_type='int8')
        stt.load_seconds=1.25
        stt.model=Mock()
        stt.model.transcribe.return_value=(iter(segments),SimpleNamespace(language='ko',duration=3,duration_after_vad=2))
        return stt

    def test_korean_transcription_not_translation_and_generator_consumed(self):
        segment=SimpleNamespace(id=0,start=0,end=2,text=' \uac80\uc740 \uc9c0\uac11 ',avg_logprob=-.2,no_speech_prob=.01)
        stt=self.make_transcriber([segment])
        with tempfile.TemporaryDirectory() as tmp, patch('speech.transcriber.version',return_value='test'):
            path=Path(tmp)/'voice.wav'
            path.write_bytes(b'placeholder')
            result=stt.transcribe(path)
        self.assertEqual(result['text'],'\uac80\uc740 \uc9c0\uac11')
        self.assertEqual(result['status'],'transcribed')
        self.assertTrue(result['requires_confirmation'])
        options=stt.model.transcribe.call_args.kwargs
        self.assertEqual(options['language'],'ko')
        self.assertEqual(options['task'],'transcribe')
        self.assertTrue(options['vad_filter'])
        self.assertEqual(len(result['segments']),1)

    def test_silence_has_no_matchable_text(self):
        stt=self.make_transcriber([])
        with tempfile.TemporaryDirectory() as tmp, patch('speech.transcriber.version',return_value='test'):
            path=Path(tmp)/'silence.wav'
            path.touch()
            result=stt.transcribe(path)
        self.assertEqual(result['status'],'no_speech')
        self.assertEqual(result['text'],'')
        stt.close()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'closed.wav'
            path.touch()
            with self.assertRaises(RuntimeError):
                stt.transcribe(path)

    def test_missing_audio_is_rejected_before_inference(self):
        stt=self.make_transcriber([])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                stt.transcribe(Path(tmp)/'missing.wav')
        stt.model.transcribe.assert_not_called()


class SpeechGpuLeaseTests(unittest.TestCase):
    """11/4 관제탑 연동: cuda 면 모델을 올리기 전에 GPU 사용권("stt"), close() 때 반납."""

    def test_close_releases_lease(self):
        import os
        from agents.gpu_lease import GpuLease, holder
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "gpu.lock"
            stt = KoreanTranscriber.__new__(KoreanTranscriber)
            stt.model = object()
            stt._lease = GpuLease("stt", path=lock).acquire()
            self.assertEqual(holder(lock)["user"], "stt")
            stt.close()
            self.assertIsNone(holder(lock))
            self.assertIsNone(stt.model)

    def test_busy_gpu_blocks_cuda_load(self):
        import os
        from agents.gpu_lease import GpuBusy, GpuLease
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "gpu.lock"
            env = {"GPU_LEASE_FILE": str(lock), "STT_GPU_WAIT": "0"}
            with GpuLease("vla", path=lock), patch.dict(os.environ, env), \
                 patch.object(KoreanTranscriber, "_load") as load:
                with self.assertRaises(GpuBusy):
                    KoreanTranscriber(SpeechConfig())        # 기본 cuda
            load.assert_not_called()

    def test_cpu_needs_no_lease_and_load_failure_releases(self):
        import os
        from agents.gpu_lease import holder
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "gpu.lock"
            with patch.dict(os.environ, {"GPU_LEASE_FILE": str(lock)}), patch.object(KoreanTranscriber, "_load"):
                stt = KoreanTranscriber(SpeechConfig(model='small', device='cpu', compute_type='int8'))
                self.assertIsNone(stt._lease)
            with patch.dict(os.environ, {"GPU_LEASE_FILE": str(lock)}), \
                 patch.object(KoreanTranscriber, "_load", side_effect=RuntimeError("모델 없음")):
                with self.assertRaises(RuntimeError):
                    KoreanTranscriber(SpeechConfig())
            self.assertIsNone(holder(lock))                     # 올리다 실패해도 열쇠 반납
