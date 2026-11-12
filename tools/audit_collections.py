"""Read-only LF-9 audit; uses existing process environment and never loads .env."""
import argparse
import json
import os
from center.collection_audit import audit_collections


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=50, choices=range(1, 201), metavar='1..200')
    args = parser.parse_args(argv)
    dsn = os.environ.get('DATABASE_URL')
    def connect():
        import psycopg
        return psycopg.connect(dsn, connect_timeout=3)
    result = audit_collections(connect if dsn else None, args.limit)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if not result['completed'] else (1 if result['issue_count'] else 0)


if __name__ == '__main__':
    raise SystemExit(main())
