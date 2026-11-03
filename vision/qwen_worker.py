"""Run under the external Qwen Python; never install or modify its dependencies."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import site
import sys
from time import perf_counter


def save(path, report):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qwen-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--site-packages", type=Path)
    args = parser.parse_args()
    if args.site_packages:
        site.addsitedir(str(args.site_packages.resolve()))
    sys.path.insert(0, str(args.qwen_root.resolve()))
    from config.settings import Settings
    from item_features import extract_item_features, SCHEMA_VERSION
    report = json.loads(args.report.read_text(encoding="utf-8"))
    output = args.report.parent / "qwen"
    output.mkdir(exist_ok=True)
    settings = replace(Settings(), log_dir=output / "logs", max_edge=512, offline=True)
    report["sequence"]["qwen_model"] = settings.model_id
    report["sequence"]["qwen_schema"] = SCHEMA_VERSION
    failed = 0
    for obj in report["objects"]:
        started = perf_counter()
        before = set(settings.log_dir.glob("benchmark-*.json"))
        try:
            features = extract_item_features(obj["crop_path"], settings)
            feature_path = output / f'object_{obj["id"]}.json'
            feature_path.write_text(json.dumps(features, ensure_ascii=False, indent=2), encoding="utf-8")
            obj["qwen"] = {"status": "ok", "features": features, "result_path": str(feature_path)}
        except Exception as error:
            failed += 1
            obj["qwen"] = {"status": "failed", "features": None, "error": str(error)}
        obj["qwen"]["elapsed_seconds"] = perf_counter()-started
        records = set(settings.log_dir.glob("benchmark-*.json"))-before
        if records:
            record = max(records, key=lambda p: p.stat().st_mtime_ns)
            obj["qwen"]["benchmark"] = json.loads(record.read_text(encoding="utf-8"))
        save(args.report, report)
        print(f'object_{obj["id"]}: {obj["qwen"]["status"]}', flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
