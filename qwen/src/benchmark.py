import csv
import json
from datetime import datetime, timezone
from uuid import uuid4

def save_record(record, log_dir):
    log_dir.mkdir(parents=True, exist_ok=True)
    record = {'timestamp': datetime.now(timezone.utc).isoformat(), **record}
    target = log_dir / f'benchmark-{uuid4().hex}'
    target.with_suffix('.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    with target.with_suffix('.csv').open('w', newline='', encoding='utf-8-sig') as out:
        writer = csv.DictWriter(out, fieldnames=list(record))
        writer.writeheader()
        writer.writerow(record)
    print(json.dumps(record, ensure_ascii=False))
