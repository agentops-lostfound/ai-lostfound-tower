"""Download public model weights; never upload local photos or records."""
from huggingface_hub import snapshot_download
from .config import MODEL_IDS

if __name__=='__main__':
    for model in MODEL_IDS.values():
        print('Preparing:',model,flush=True)
        path=snapshot_download(model,allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.jinja'],max_workers=3)
        print('Ready:',path,flush=True)
