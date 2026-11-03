import importlib.metadata
import platform
import shutil
import subprocess
import sys

def check_environment():
    import psutil
    report = {'python': sys.version, 'executable': sys.executable,
              'architecture': platform.machine(), 'platform': platform.platform(),
              'cpu': platform.processor(), 'cpu_count': psutil.cpu_count(),
              'ram_free_bytes': psutil.virtual_memory().available,
              'ram_total_bytes': psutil.virtual_memory().total,
              'disk_free_bytes': shutil.disk_usage('.').free}
    for name in ['torch', 'torchvision', 'torchaudio', 'transformers', 'accelerate',
                 'bitsandbytes', 'Pillow', 'pydantic', 'pytest']:
        try:
            report[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report[name] = None
    try:
        report['nvidia_smi'] = subprocess.run(['nvidia-smi'], capture_output=True,
                                             text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        report['nvidia_smi'] = str(exc)
    try:
        import torch
        import torchvision
        from transformers import Qwen3VLForConditionalGeneration, AutoProcessor
        report.update(cuda_available=torch.cuda.is_available(), cuda_build=torch.version.cuda,
                      processor_import=True, torchvision_import=True)
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            report.update(gpu=p.name, vram_bytes=p.total_memory)
            # Execute a real kernel, not merely a driver availability query.
            report['cuda_kernel'] = (torch.ones(2, device='cuda') * 2).sum().item() == 4
    except Exception as exc:
        report['import_error'] = str(exc)
    return report
