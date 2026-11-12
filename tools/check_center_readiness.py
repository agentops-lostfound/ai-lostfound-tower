"""Inspect LF-9 schema/role readiness using existing process environment; never loads .env."""
import json
from agents.center_integration import environment_services
from center.readiness import check_readiness


def main():
    stores = environment_services()
    result = check_readiness(getattr(stores['collections'], 'connect', None),
                             getattr(stores['statistics'], 'connect', None))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
