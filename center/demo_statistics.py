"""Same closed question planner; isolated SQLite view, query-only and authorizer."""
import sqlite3
from datetime import datetime
from center.statistics import plan_count, count_response


def authorize_statistics(action, table, column, database, source):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_TRANSACTION):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column == 'count':
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main':
        if table == 'demo_stats_item' or (table == 'demo_item' and source == 'demo_stats_item'
                                         and column in ('received_at', 'machine_id', 'category')):
            return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


class DemoStatistics:
    def __init__(self, store):
        self.store = store

    def ask(self, question, now=None, *, revision=None):
        query = plan_count(question, now)
        sql = query.sql.replace('public.stats_item', 'demo_stats_item').replace('%s', '?')
        params = tuple(int(v.timestamp() * 1_000_000) if isinstance(v, datetime) else v for v in query.params)
        with self.store.connection() as db:
            current = self.store._check_revision(db, revision)
            db.set_authorizer(authorize_statistics)
            count = db.execute(sql, params).fetchone()[0]
        return {**count_response(query, count, sql, params, 'demo_stats_item', 'demo_sqlite'), 'revision': current}
