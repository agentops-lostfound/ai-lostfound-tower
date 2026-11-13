from functools import lru_cache
from time import perf_counter
from dataclasses import dataclass
from config.settings import Settings

@dataclass
class ModelBundle:
    model: object
    processor: object
    metadata: dict

@lru_cache(maxsize=1)
def load_model(settings: Settings = Settings()):
    import torch
    import transformers
    import bitsandbytes as bnb
    from huggingface_hub import snapshot_download
    from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable. GPU inference is required; CPU fallback is disabled.')
    start = perf_counter()
    # Explicit download phase allows load time to exclude network transfer.
    local = snapshot_download(settings.model_id, cache_dir=str(settings.cache_dir),
                              local_files_only=settings.offline,
                              allow_patterns=['*.json', '*.safetensors', '*.txt', '*.jinja', '*.model'])
    download_seconds = perf_counter() - start
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    start = perf_counter()
    try:
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            local, local_files_only=True,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True,
                bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True),
            device_map={'': 0}, dtype=torch.float16, attn_implementation='sdpa')
        processor = AutoProcessor.from_pretrained(local, local_files_only=True)
        model.eval()
        non_gpu = [(n, str(p.device)) for n, p in model.named_parameters() if p.device.type != 'cuda']
        layers = [m for m in model.modules() if isinstance(m, bnb.nn.Linear4bit)]
        if non_gpu:
            raise RuntimeError(f'CPU/disk placement detected: {non_gpu[:5]}')
        if not getattr(model, 'is_loaded_in_4bit', False) or not layers:
            raise RuntimeError('4-bit quantization was not applied')
        if any(m.weight.quant_state is None for m in layers):
            raise RuntimeError('Uninitialized 4-bit quantization state')
        if any(m.weight.quant_state.quant_type != 'nf4' for m in layers):
            raise RuntimeError('Unexpected 4-bit quantization type (NF4 required)')
        torch.cuda.synchronize()
    except torch.cuda.OutOfMemoryError as exc:
        raise RuntimeError('CUDA OOM during loading. Free GPU memory; no CPU fallback was used.') from exc
    metadata = dict(gpu=torch.cuda.get_device_name(0), torch=torch.__version__,
                    cuda=torch.version.cuda, transformers=transformers.__version__,
                    quantization='4-bit NF4 / float16', quantized_layers=len(layers),
                    model_id=settings.model_id, snapshot=local,
                    download_or_cache_seconds=download_seconds,
                    model_load_seconds=perf_counter()-start,
                    model_allocated_bytes=torch.cuda.memory_allocated(),
                    load_peak_vram_allocated_bytes=torch.cuda.max_memory_allocated())
    print(metadata)
    return ModelBundle(model, processor, metadata)
