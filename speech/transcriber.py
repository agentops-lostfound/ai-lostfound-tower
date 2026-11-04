"""Local faster-whisper transcription with explicit device and Korean output."""
from dataclasses import dataclass
from importlib.metadata import version
import os
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SpeechConfig:
    model: str = 'large-v3-turbo'
    device: str = 'cuda'
    compute_type: str = 'int8_float16'
    beam_size: int = 5
    cpu_threads: int = 2
    offline: bool = False
    vad_filter: bool = True
    cache_dir: Path = ROOT / '.cache/speech'
    cuda_lib_dirs: tuple = ()

    def validate(self):
        if self.model not in ('small', 'large-v3-turbo'):
            raise ValueError('Use multilingual small or large-v3-turbo')
        if self.device not in ('cpu','cuda') or self.compute_type not in ('int8','float32','float16','int8_float16'):
            raise ValueError('Invalid device or compute type')
        if self.device=='cpu' and self.compute_type not in ('int8','float32'):
            raise ValueError('CPU requires int8 or float32')
        if not 1 <= self.beam_size <= 10 or not 1 <= self.cpu_threads <= 32:
            raise ValueError('beam_size must be 1..10; cpu_threads 1..32')


class KoreanTranscriber:
    """Keep one instance for repeated requests; close/release before loading a VLM."""
    def __init__(self, config=None):
        self.config = config or SpeechConfig()
        self.config.validate()
        self._dll_handles=[]
        for directory in self.config.cuda_lib_dirs:
            directory=Path(directory).resolve()
            if not directory.is_dir():
                raise ValueError('CUDA library directory does not exist')
            if os.name=='nt':
                self._dll_handles.append(os.add_dll_directory(str(directory)))
                # Native DLL loaders may also use PATH rather than AddDllDirectory.
                os.environ['PATH']=str(directory)+os.pathsep+os.environ.get('PATH','')
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model
        import ctranslate2
        started=perf_counter()
        if self.config.device=='cuda' and ctranslate2.get_cuda_device_count()<1:
            raise RuntimeError('CUDA unavailable; choose --device cpu explicitly. No silent fallback.')
        local=self.config.cache_dir/self.config.model
        required=('model.bin','config.json','tokenizer.json','vocabulary.json')
        if not all((local/name).is_file() and (local/name).stat().st_size>0 for name in required):
            local=Path(download_model(self.config.model,output_dir=str(local),local_files_only=self.config.offline))
        if not all((local/name).is_file() and (local/name).stat().st_size>0 for name in required):
            raise RuntimeError('STT model cache is incomplete; download the model before --offline')
        self.model=WhisperModel(str(local),device=self.config.device,
                   compute_type=self.config.compute_type,cpu_threads=self.config.cpu_threads,
                   download_root=str(self.config.cache_dir),local_files_only=self.config.offline)
        self.load_seconds=perf_counter()-started

    def transcribe(self, audio_path):
        path=Path(audio_path).resolve()
        if not path.is_file():
            raise ValueError('Audio file does not exist')
        if self.model is None:
            raise RuntimeError('Transcriber is closed')
        started=perf_counter()
        segments,info=self.model.transcribe(str(path),language='ko',task='transcribe',
            beam_size=self.config.beam_size,vad_filter=self.config.vad_filter,
            condition_on_previous_text=False,temperature=0.0)
        # Consuming the generator is necessary to include actual inference in timing.
        rows=[{'id':s.id,'start':float(s.start),'end':float(s.end),'text':s.text.strip(),
               'avg_logprob':float(s.avg_logprob),'no_speech_prob':float(s.no_speech_prob)} for s in segments]
        text=' '.join(s['text'] for s in rows if s['text']).strip()
        elapsed=perf_counter()-started
        return {'schema':'speech.transcript.v1','status':'transcribed' if text else 'no_speech',
                'text':text,'language':info.language,'task':'transcribe','source':str(path),
                'segments':rows,'requires_confirmation':True,
                'runtime':{'model':self.config.model,'device':self.config.device,
                   'compute_type':self.config.compute_type,'vad_filter':self.config.vad_filter,
                   'beam_size':self.config.beam_size,'faster_whisper':version('faster-whisper'),
                   'ctranslate2':version('ctranslate2')},
                'timing':{'model_load_seconds':self.load_seconds,'transcribe_seconds':elapsed,
                   'audio_seconds':float(info.duration),
                   'audio_after_vad_seconds':float(info.duration_after_vad),
                   'real_time_factor':elapsed/info.duration if info.duration>0 else None},
                'notice':'Review the Korean transcript before matching. Segment metrics are not item confidence. No automatic matching or robot action.'}

    def close(self):
        self.model=None
        # Keep native library search handles until process exit; a second instance may use them.

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()
