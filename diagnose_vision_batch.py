"""Read existing vision batch summary and Qwen JSON. No models or robot invoked."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from vision.adapter_diagnostics import diagnose_report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-dir", type=Path, required=True)
    args = ap.parse_args()
    source = args.batch_dir / "summary.csv"
    with source.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    summary = []
    details = []
    overall = Counter()
    for row in rows:
        path = Path(row["result_json"])
        image = Path(row["image"]).name
        if not path.is_file():
            diagnostic = {"reason_counts": {"missing_result_json": 1}, "objects": [],
                          "detected_count": 0, "accepted_preview_count": 0,
                          "actual_adapter_count": 0, "scene_complete": False}
        else:
            try:
                report = json.loads(path.read_text(encoding="utf-8-sig"))
                diagnostic = diagnose_report(report, require_calibration=False)
            except (OSError, ValueError, TypeError):
                diagnostic = {"reason_counts": {"unreadable_result_json": 1}, "objects": [],
                              "detected_count": 0, "accepted_preview_count": 0,
                              "actual_adapter_count": 0, "scene_complete": False}
        overall.update(diagnostic["reason_counts"])
        summary.append({"image": image, "yolo_detected": diagnostic["detected_count"],
                        "accepted_preview": diagnostic["accepted_preview_count"],
                        "actual_adapter": diagnostic["actual_adapter_count"],
                        "scene_complete": diagnostic["scene_complete"],
                        "reasons": ";".join(f"{k}:{v}" for k, v in diagnostic["reason_counts"].items())})
        details.append({"image": image, "objects": diagnostic["objects"],
                        "reason_counts": diagnostic["reason_counts"]})
    out_csv = args.batch_dir / "adapter_diagnostics_summary.csv"
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary[0]) if summary else ["image", "yolo_detected", "accepted_preview", "actual_adapter", "scene_complete", "reasons"])
        writer.writeheader()
        writer.writerows(summary)
    out_json = args.batch_dir / "adapter_diagnostics_details.json"
    out_json.write_text(json.dumps({"inspection_only": True, "overall_reason_counts": dict(overall),
                                    "images": details}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Analyzed {len(summary)} existing reports; no inference rerun")
    print("Reason counts:", dict(overall))
    print("CSV:", out_csv)
    print("JSON:", out_json)


if __name__ == "__main__":
    main()
