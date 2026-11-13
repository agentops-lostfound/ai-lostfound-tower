"""격리된 CUDA 프로세스. stdin 한 건 → stdout JSON 한 건, 모델 해제 후 종료."""
from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import sys
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--locator-root", required=True)
    args = parser.parse_args()
    request = json.loads(sys.stdin.readline())
    with contextlib.redirect_stdout(sys.stderr):
        sys.path.insert(0, args.locator_root)
        from PIL import Image
        from locate_objects import locate, load_settings, Models, Store, DATA
        from beta.config import MODEL_IDS
        from pathlib import Path
        model_root = Path(args.locator_root).parent / "models"
        for key, name in (("owl", "owlv2-base-patch16-ensemble"), ("sig", "siglip2-base-patch16-224")):
            if (model_root / name / "model.safetensors").exists():
                MODEL_IDS[key] = str(model_root / name)
        models = Models(lambda *args, **kwargs: None, threading.Event())
        # Host GPU lease stays held until this child exits. Sequential loading fits RTX3050 6GB.
        models.resident_enabled = False
        try:
            image = Image.open(io.BytesIO(base64.b64decode(request["jpeg"]))).convert("RGB")
            settings = load_settings()
            settings["roi"] = request.get("roi")
            result = locate(image, settings, Store(DATA / "vision.sqlite3"), models)
            # The ZIP retains retired wallet/USB references. Keep these as review candidates,
            # rather than counting them as one of the four current operational item types.
            for obj in result["objects"]:
                if obj["quality"] == "accepted" and obj["category"] not in {"phone", "power_bank", "hand_cream", "lip_balm"}:
                    obj["quality"] = "review"
                    obj["reasons"].append("현재 운영 품목 외 후보 — 실물/부분 검출 검토")
            for quality in ("accepted", "review", "rejected"):
                result["counts"][quality] = sum(obj["quality"] == quality for obj in result["objects"])
        finally:
            models.release()
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
