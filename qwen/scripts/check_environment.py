import argparse
import json
from pathlib import Path
from src.device_check import check_environment

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--load-model', action='store_true', help='May download several GB on first run')
    args = parser.parse_args()
    report = check_environment()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    Path('logs').mkdir(exist_ok=True)
    Path('logs/environment.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not report.get('cuda_kernel') or report.get('import_error'):
        return 1
    if args.load_model:
        from src.model_loader import load_model
        from src.benchmark import save_record
        from config.settings import Settings
        try:
            bundle = load_model()
        except Exception as exc:
            save_record({'model_load_success': False, 'error': str(exc)}, Settings().log_dir)
            print(f'Model load failed: {exc}')
            return 1
        save_record({'model_load_success': True, **bundle.metadata}, Settings().log_dir)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
