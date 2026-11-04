"""YOLO 학습 파이프라인 (집 PC용, LF-3): 받기 → 학습 → 검증 → 내보내기 → 올리기 → 디스코드 알림.

한줄 설명: 집 PC 팀원은 이 파일 하나만 실행하면 되고, 결과는 Hub에 올라가 교육원에서 누구나 받을 수 있다.

사용법 (집 PC)
    python vision/train_yolo.py --dataset vision_v1103 --name yolo26n_v1103 --download --upload
교육원 PC에서 작은 시험 (학습 2에폭)
    python vision/train_yolo.py --dataset vision_v1103 --name smoke --epochs 2 --batch 4
무엇을 할지만 확인
    python vision/train_yolo.py --dataset vision_v1103 --name yolo26n_v1103 --dry-run

결과 (models/<name>/)
    best.pt · best.onnx · best_openvino_model/ · metrics.json · data.yaml
- 학습이 실패해도 디스코드로 '실패' 알림을 보낸다(밤사이 실패를 아침에 바로 알 수 있게).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.envfile import load_env  # noqa: E402
from tools.notify import notify  # noqa: E402
from vision.config import CLASSES  # noqa: E402

DATASETS = Path("datasets")
MODELS = Path("models")


def write_abs_yaml(dataset_dir: Path, dst: Path) -> Path:
    """data.yaml의 path를 '지금 PC의 절대 경로'로 바꾼 사본을 만든다(교육원↔집 PC 경로 차이 해결)."""
    src = dataset_dir / "data.yaml"
    if not src.is_file():
        raise SystemExit(f"data.yaml 이 없습니다: {src} (prepare_dataset.py 로 먼저 만드세요)")
    lines = src.read_text(encoding="utf-8").splitlines()
    body = [ln for ln in lines if not ln.startswith("path:")]
    text = f"path: {dataset_dir.resolve().as_posix()}\n" + "\n".join(body) + "\n"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    return dst


def count_images(dataset_dir: Path) -> dict[str, int]:
    return {s: len(list((dataset_dir / "images" / s).glob("*.jpg"))) for s in ("train", "val")}


def train(a: argparse.Namespace) -> dict:
    from ultralytics import YOLO  # 무거운 패키지라 실제 학습할 때만 불러온다

    out_dir = MODELS / a.name
    data_yaml = write_abs_yaml(DATASETS / a.dataset, out_dir / "data.yaml")
    model = YOLO(a.model)
    t0 = time.time()
    model.train(
        data=str(data_yaml),
        epochs=a.epochs,
        imgsz=a.imgsz,
        batch=a.batch,
        device=a.device,
        project=str(Path("runs").resolve()),
        name=a.name,
        exist_ok=True,
        seed=0,
        patience=a.patience,
        verbose=True,
    )
    minutes = (time.time() - t0) / 60
    best = Path(model.trainer.best)
    best_model = YOLO(str(best))
    m = best_model.val(data=str(data_yaml), imgsz=a.imgsz, split="val", verbose=False)
    per_class = {CLASSES[i]: round(float(v), 4) for i, v in enumerate(m.box.maps[: len(CLASSES)])}
    metrics = {
        "name": a.name,
        "dataset": a.dataset,
        "base_model": a.model,
        "epochs": a.epochs,
        "imgsz": a.imgsz,
        "batch": a.batch,
        "train_minutes": round(minutes, 1),
        "images": count_images(DATASETS / a.dataset),
        "mAP50": round(float(m.box.map50), 4),
        "mAP50-95": round(float(m.box.map), 4),
        "mAP50-95_per_class": per_class,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, out_dir / "best.pt")
    if not a.no_export:
        onnx = Path(best_model.export(format="onnx", imgsz=a.imgsz))
        shutil.copy2(onnx, out_dir / "best.onnx")
        ov = Path(best_model.export(format="openvino", imgsz=a.imgsz))
        shutil.copytree(ov, out_dir / "best_openvino_model", dirs_exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def summary(m: dict) -> str:
    cls = " · ".join(f"{k} {v:.2f}" for k, v in m["mAP50-95_per_class"].items())
    return (
        f"데이터 {m['dataset']} (train {m['images']['train']} / val {m['images']['val']})\n"
        f"mAP50 {m['mAP50']:.3f} · mAP50-95 {m['mAP50-95']:.3f}\n"
        f"품목별 {cls}\n"
        f"학습 {m['train_minutes']}분 · {m['epochs']}에폭 · batch {m['batch']}"
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="YOLO 학습 파이프라인")
    ap.add_argument("--dataset", required=True, help="datasets/ 아래 폴더 이름 (예: vision_v1103)")
    ap.add_argument("--name", required=True, help="결과 이름 (예: yolo26n_v1103)")
    ap.add_argument("--model", default="yolo26n.pt", help="시작 가중치 (기본 yolo26n.pt, 11/4 확정)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16, help="RTX 4070 SUPER 16, 교육원 RTX 3050은 4~8 권장(추정)")
    ap.add_argument("--patience", type=int, default=30, help="이 에폭 동안 나아지지 않으면 조기 종료")
    ap.add_argument("--device", default="0", help="GPU 번호, CPU면 cpu")
    ap.add_argument("--download", action="store_true", help="학습 전에 Hub에서 데이터셋 받기")
    ap.add_argument("--upload", action="store_true", help="학습 후 models/<name> 을 Hub에 올리기")
    ap.add_argument("--no-export", action="store_true", help="ONNX·OpenVINO 내보내기 생략")
    ap.add_argument("--no-notify", action="store_true", help="디스코드 알림 끄기")
    ap.add_argument("--dry-run", action="store_true", help="무엇을 할지만 출력")
    return ap


def main(argv: list[str] | None = None) -> int:
    load_env()
    a = build_parser().parse_args(argv)
    say = (lambda t, b: None) if a.no_notify else notify
    from tools import hub_sync

    if a.dry_run:
        print(f"[계획] 데이터 datasets/{a.dataset} · 시작 가중치 {a.model} · {a.epochs}에폭 · imgsz {a.imgsz} · batch {a.batch} · device {a.device}")
        if a.download:
            hub_sync.download("data", a.dataset, DATASETS / a.dataset, dry_run=True)
        print(f"[계획] 결과 models/{a.name}/ (best.pt" + ("" if a.no_export else ", best.onnx, best_openvino_model") + ", metrics.json)")
        if a.upload:
            hub_sync.upload("model", MODELS / a.name, a.name, dry_run=True) if (MODELS / a.name).is_dir() else print(f"[계획] 학습 후 models/{a.name} 을 Hub 모델 저장소에 올림")
        print(f"[계획] 디스코드 알림: {'끔' if a.no_notify else '시작·완료·실패'}")
        return 0

    try:
        if a.download:
            hub_sync.download("data", a.dataset, DATASETS / a.dataset, dry_run=False)
        say("🏋️ 학습 시작", f"{a.name} · 데이터 {a.dataset} · {a.epochs}에폭")
        m = train(a)
        if a.upload:
            hub_sync.upload("model", MODELS / a.name, a.name, dry_run=False)
        say("✅ 학습 완료", summary(m) + (f"\nHub 모델 저장소 · {a.name}" if a.upload else ""))
        print(summary(m))
        return 0
    except SystemExit as e:
        say("❌ 학습 중단", f"{a.name} · {e}")
        raise
    except Exception as e:  # 밤사이 실패를 바로 알 수 있게 오류 종류와 마지막 줄만 알림
        last = traceback.format_exc().strip().splitlines()[-1][:300]
        say("❌ 학습 실패", f"{a.name} · {type(e).__name__}\n{last}")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
