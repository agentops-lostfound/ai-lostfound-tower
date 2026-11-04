import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from speech.transcriber import SpeechConfig, KoreanTranscriber


class SpeechTests(unittest.TestCase):
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
