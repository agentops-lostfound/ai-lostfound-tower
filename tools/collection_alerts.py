"""LF-9: queue overdue pickups; preview alerts by default. Sending is explicit."""
import argparse
import os
from datetime import datetime
from center.collections import CollectionStore
from discord_ops.reporter import Reporter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True, help="Explicit overdue cutoff, including timezone")
    parser.add_argument("--send", action="store_true", help="Actually send Discord notifications")
    args = parser.parse_args()
    import psycopg
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL을 실행 환경에 설정하세요")
    store = CollectionStore(lambda: psycopg.connect(dsn, connect_timeout=5))
    cutoff = datetime.fromisoformat(args.before)
    queued = store.overdue(cutoff)
    reporter = Reporter(dry_run=not args.send)
    sent = store.dispatch(reporter)
    print({"queued": queued, "preview_count": len(reporter.messages), "sent": sent, "dry_run": reporter.dry_run})


if __name__ == "__main__":
    main()
