"""Train an independent one-class detector without changing the team's taxonomy."""
import argparse
import json
from pathlib import Path
import shutil
import yaml

ROOT = Path(__file__).resolve().parents[2]


def training_plan(data, name):
    data = Path(data).resolve()
    config = yaml.safe_load(data.read_text(encoding="utf-8"))
    if config.get("names") not in ({0: "item"}, ["item"]):
        raise ValueError("This trainer requires exactly one class: 0=item")
    if Path(name).name != name or name in (".", "..") or "\\" in name:
        raise ValueError("name must be a single directory name")
    dataset = Path(config["path"])
    if not dataset.is_absolute():
        dataset = (data.parent / dataset).resolve()
    config["path"] = str(dataset)
    return config, ROOT / "models" / name


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT / "vision/configs/data_item.yaml")
    parser.add_argument("--name", default="item_baseline")
    parser.add_argument("--model", default=str(ROOT / "models/yolo26l.pt"))
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        config, output = training_plan(args.data, args.name)
        if args.dry_run:
            print(json.dumps({"data": config, "output": str(output), "model": args.model,
                              "device": args.device, "epochs": args.epochs,
                              "batch": args.batch, "imgsz": args.imgsz}, indent=2))
            return 0
        if output.exists():
            raise ValueError(f"Output exists; use a new --name: {output}")
        for split in ("train", "val"):
            images = Path(config["path"]) / config[split]
            if not images.is_dir() or not any(p.suffix.lower() in {".jpg", ".jpeg", ".png"} for p in images.iterdir()):
                raise ValueError(f"Missing images for {split}: {images}")
            labels = Path(config["path"]) / "labels" / split
            files = list(labels.glob("*.txt"))
            positive = False
            for label in files:
                for line in label.read_text(encoding="utf-8-sig").splitlines():
                    fields = line.split()
                    if not fields:
                        continue
                    if len(fields) != 5 or fields[0] != "0":
                        raise ValueError(f"Expected YOLO bbox class 0=item: {label}")
                    coords = list(map(float, fields[1:]))
                    if not all(0 <= v <= 1 for v in coords) or coords[2] <= 0 or coords[3] <= 0:
                        raise ValueError(f"Invalid normalized bbox: {label}")
                    positive = True
            if not positive:
                raise ValueError(f"No positive item labels for {split}: {labels}")
        from ultralytics import YOLO
        output.mkdir(parents=True)
        resolved = output / "data.yaml"
        resolved.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        model = YOLO(args.model)
        model.train(data=str(resolved), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                    device=args.device, project=str(ROOT / "runs/item"), name=args.name,
                    exist_ok=False, seed=0)
        best = Path(model.trainer.best)
        shutil.copy2(best, output / "best.pt")
        print(f"Trained weights: {output / 'best.pt'}")
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Item training failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
