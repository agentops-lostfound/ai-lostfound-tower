"""Read-only schema and statistics role checks. No credentials or records returned."""


def check_readiness(write_connect, read_connect):
    identities = []
    result = {'ready': False, 'collection': 'not_configured', 'statistics': 'not_configured',
              'same_database': False,
              'scope': '필수 스키마와 통계 역할 점검 · 실제 업무 쓰기 성공 검증 아님'}
    if write_connect:
        try:
            with write_connect() as conn, conn.cursor() as cur:
                cur.execute('SET TRANSACTION READ ONLY')
                cur.execute("SET LOCAL statement_timeout = '3s'")
                cur.execute("SELECT to_regclass('public.collection'),to_regclass('public.collection_item'),to_regclass('public.collection_alert'),to_regclass('public.item_status_log')")
                tables = cur.fetchone()
                cur.execute("SELECT EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid=to_regclass('public.collection') AND attname='request_id' AND NOT attisdropped)")
                column = cur.fetchone()[0]
                cur.execute('SELECT inet_server_addr()::text,inet_server_port(),current_database()')
                identities.append(cur.fetchone())
                result['collection'] = 'ready' if all(tables) and column else 'schema_missing'
        except Exception:
            result['collection'] = 'unavailable'
    if read_connect:
        try:
            with read_connect() as conn, conn.cursor() as cur:
                cur.execute('SET TRANSACTION READ ONLY')
                cur.execute('SET LOCAL ROLE lf_stats_reader')
                cur.execute("SET LOCAL statement_timeout = '3s'")
                cur.execute("SELECT has_table_privilege(current_user,'public.stats_item','SELECT'),has_table_privilege(current_user,'public.item','SELECT'),has_table_privilege(current_user,'public.claim','SELECT'),has_table_privilege(current_user,'public.finder_contact','SELECT')")
                allowed, *private = cur.fetchone()
                cur.execute('SELECT inet_server_addr()::text,inet_server_port(),current_database()')
                identities.append(cur.fetchone())
                result['statistics'] = 'ready' if allowed and not any(private) else 'unsafe_permissions'
        except Exception:
            result['statistics'] = 'unavailable'
    result['same_database'] = len(identities) == 2 and identities[0] == identities[1]
    result['ready'] = result['collection'] == result['statistics'] == 'ready' and result['same_database']
    return result
