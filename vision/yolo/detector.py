from pathlib import Path
import os

os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).resolve().parents[2] / "outputs" / ".ultralytics"))
import numpy as np


def runtime_info(device="auto"):
    import torch
    available = torch.cuda.is_available()
    if device != "auto" and device != "cpu" and not available:
        raise RuntimeError("CUDA requested but unavailable; use --device cpu")
    selected = ("0" if available else "cpu") if device == "auto" else device
    return {"device": selected, "cuda_available": available,
            "torch_version": torch.__version__, "cuda_version": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if available else None}


class YoloDetector:
    def __init__(self, model_path, device="auto", confidence=0.25, imgsz=640):
        from ultralytics import YOLO
        self.runtime = runtime_info(device)
        path = Path(model_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            if path.name != "yolo26n.pt":
                raise FileNotFoundError(f"Custom weights not found: {path}")
            # Ultralytics downloads the named official asset into the requested directory.
            from ultralytics.utils.downloads import attempt_download_asset
            path = Path(attempt_download_asset(str(path)))
        self.model = YOLO(str(path))
        self.confidence, self.imgsz = confidence, imgsz

    def detect(self, image):
        result = self.model.predict(source=image, device=self.runtime["device"],
                                    conf=self.confidence, imgsz=self.imgsz, verbose=False)[0]
        objects = []
        for box in result.boxes:
            bbox = box.xyxy[0].cpu().tolist()
            if not np.isfinite(bbox).all() or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            objects.append({"id": len(objects), "class_id": int(box.cls.item()),
                            "class_name": result.names[int(box.cls.item())],
                            "confidence": float(box.conf.item()), "bbox": bbox,
                            "center_px": [(bbox[0]+bbox[2])/2, (bbox[1]+bbox[3])/2]})
        return objects
