"""Opt-in, isolated PostgreSQL verification. Requires existing Docker and postgres:16 image."""
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path


def main():
    import psycopg
    from psycopg.conninfo import make_conninfo
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['docker', 'image', 'inspect', 'postgres:16'], check=True, stdout=subprocess.DEVNULL)
    env = os.environ.copy()
    password = secrets.token_hex(24)
    env['POSTGRES_PASSWORD'] = password
    container = subprocess.check_output(['docker', 'run', '--pull=never', '--rm', '-d', '--name',
        'lf9-check-' + secrets.token_hex(5), '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_DB=lf_support_test',
        '-p', '127.0.0.1::5432', 'postgres:16'], env=env, text=True).strip()
    if not re.fullmatch(r'[0-9a-f]{64}', container):
        raise RuntimeError('검증용 컨테이너 식별자를 확인하지 못했습니다')
    try:
        address = subprocess.check_output(['docker', 'port', container, '5432/tcp'], text=True).strip()
        if not re.fullmatch(r'127\.0\.0\.1:[0-9]+', address):
            raise RuntimeError('로컬 검증 포트를 확인하지 못했습니다')
        dsn = make_conninfo(host='127.0.0.1', port=int(address.rsplit(':', 1)[1]), user='postgres',
                           password=password, dbname='lf_support_test', connect_timeout=2)
        deadline = time.monotonic() + 40
        while True:
            try:
                with psycopg.connect(dsn, autocommit=True) as db:
                    db.execute('CREATE DATABASE lf_chat_search_test')
                break
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise RuntimeError('검증용 DB가 준비되지 않았습니다') from None
                time.sleep(.3)
        test_env = os.environ.copy()
        for key in ('LF_TEST_DSN', 'DATABASE_URL', 'LF_STATS_DATABASE_URL'):
            test_env.pop(key, None)
        test_env['LF_SUPPORT_TEST_DSN'] = dsn
        test_env['LF_CHAT_SEARCH_TEST_DSN'] = make_conninfo(dsn, dbname='lf_chat_search_test')
        print('별도 임시 DB에서 전체 시험을 실행합니다. 실제 팀 DB는 연결하지 않습니다.', flush=True)
        return subprocess.run([sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'tests'],
                              cwd=root, env=test_env).returncode
    finally:
        subprocess.run(['docker', 'stop', container], check=True, stdout=subprocess.DEVNULL)
        print('직접 만든 검증 컨테이너를 정리했습니다.', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
