"""Train the top-view YOLO detector on ROOT/yolo (run as: python -m beta.detector_train).

Separate process so the server's OWL/SigLIP models and camera loop keep running.
Output: models/detector/best.pt (+ train run folder under beta_data/detector_dataset/runs).
"""
import json
import shutil
import sys
from pathlib import Path
from .config import DATA

ROOT=DATA/'detector_dataset'
BASE=Path(__file__).resolve().parent.parent/'models'/'yolo26n.pt'
OUT=Path(__file__).resolve().parent.parent/'models'/'detector'


def main(epochs=60,imgsz=960,batch=8):
    from ultralytics import YOLO
    data=ROOT/'yolo'/'data.yaml'
    if not data.exists():raise SystemExit('합성 데이터(data.yaml)가 없습니다. 먼저 데이터 만들기를 실행하세요.')
    model=YOLO(str(BASE))
    result=model.train(data=str(data),epochs=epochs,imgsz=imgsz,batch=batch,device=0,workers=2,
                       project=str(ROOT/'runs'),name='top',exist_ok=True,patience=20,
                       degrees=180,fliplr=.5,flipud=.5,mosaic=.5,verbose=False,plots=False)
    best=Path(result.save_dir)/'weights'/'best.pt'
    OUT.mkdir(parents=True,exist_ok=True);shutil.copy2(best,OUT/'best.pt')
    names=YOLO(str(best)).names
    # v0.2.66: data.yaml lists every enabled category, but only those with cut-outs/real boxes
    # were actually learned; the server lets YOLO decide alone only when this covers all.
    try:trained=sorted(json.loads((ROOT/'yolo'/'summary.json').read_text(encoding='utf-8')).get('cutouts',{}))
    except (OSError,ValueError):trained=[]
    (OUT/'meta.json').write_text(json.dumps({'names':names,'trained_classes':trained,'source':str(best),'epochs':epochs,'imgsz':imgsz},ensure_ascii=False,indent=2),encoding='utf-8')
    print('DONE',OUT/'best.pt',flush=True)


if __name__=='__main__':
    main(*(int(a) for a in sys.argv[1:]))
