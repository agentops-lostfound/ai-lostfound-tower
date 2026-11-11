"""Optional disposable PostgreSQL test only; never runs against the team database."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from agents.chat_search import PostgresItemSearch, SearchAgent
from agents.lost_input import KST

DSN = os.environ.get('LF_CHAT_SEARCH_TEST_DSN', '')


@unittest.skipUnless(DSN, 'Disposable chat search PostgreSQL DSN not configured')
class ChatPostgresSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        if conninfo_to_dict(DSN).get('dbname') != 'lf_chat_search_test':
            raise RuntimeError('Only the disposable lf_chat_search_test database is allowed')
        cls.db = PostgresItemSearch(DSN)
        cls.agent = SearchAgent(cls.db, authorize=lambda token: token == 'synthetic-verified-session')
        now = datetime.now(timezone.utc)
        loss = now.astimezone(KST).date() - timedelta(days=2)
        cls.context = {'lost_date': loss.isoformat(), 'lost_line': '1호선', 'lost_station': '중앙역'}
        with psycopg.connect(DSN) as db:
            db.execute('CREATE TABLE machine (machine_id text PRIMARY KEY, line text, station text)')
            db.execute('CREATE TABLE item (item_id text PRIMARY KEY, category text, features jsonb, status text, '
                       'machine_id text REFERENCES machine, received_at timestamptz, private_features jsonb)')
            db.execute("INSERT INTO machine VALUES ('test-A','1호선','중앙'), ('test-B','1호선','초량'), ('test-C','1호선','부산')")
            rows = [('A-W01','본센터 보관','test-A',now-timedelta(hours=1)),
                    ('A-W02','인계 완료','test-A',now-timedelta(hours=1)),
                    ('A-W03','본센터 보관','test-A',now-timedelta(days=5)),
                    ('A-W04','본센터 보관','test-B',now-timedelta(hours=2)),
                    ('A-W05','본센터 보관','test-C',now-timedelta(hours=1)),
                    ('A-W06','본센터 보관','test-A',now+timedelta(days=1))]
            for item_id,status,machine,received in rows:
                db.execute("INSERT INTO item VALUES (%s,'지갑','{\"color\":\"검정\"}',%s,%s,%s,'{\"mark\":\"synthetic-private-answer\"}')",
                           (item_id,status,machine,received))

    @classmethod
    def tearDownClass(cls):
        import psycopg
        with psycopg.connect(DSN) as db:
            db.execute('DROP TABLE item'); db.execute('DROP TABLE machine')

    def test_preferred_station_excludes_old_delivered_future_and_other_station_rows(self):
        result = self.agent.ask('검정 지갑 찾아줘','synthetic-verified-session',self.context)
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(self.agent.resolve_candidate(result['search_result_id'],1,'synthetic-verified-session'),'A-W01')
        self.assertNotIn('A-W01',str(result)); self.assertNotIn('synthetic-private-answer',str(result))

    def test_missing_station_falls_back_to_same_line_only(self):
        result = self.agent.ask('검정 지갑 찾아줘','synthetic-verified-session',{**self.context,'lost_station':'광안역'})
        self.assertEqual(len(result['candidates']),2)
        ids = [self.agent.resolve_candidate(result['search_result_id'],number,'synthetic-verified-session') for number in (1,2)]
        self.assertEqual(set(ids),{'A-W01','A-W04'})

    def test_missing_or_wrong_identity_never_returns_candidates(self):
        for token in (None,'synthetic-forged-session'):
            result = self.agent.ask('검정 지갑 찾아줘',token,self.context)
            self.assertEqual(result['status'],'authentication_required')
            self.assertFalse(result['item_search_performed'])

    def test_actual_read_only_transaction_rejects_writes(self):
        import psycopg
        with psycopg.connect(DSN) as db:
            db.read_only = True
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                db.execute("UPDATE item SET status='인계 완료'")
            db.rollback()

    def test_color_omission_and_parameterized_station_input_remain_read_only(self):
        context={**self.context,'lost_station':'중앙'}
        self.assertEqual(len(self.db.search('지갑',None,context)),1)
        result=self.db.search('지갑','검정',{**context,'lost_station':"missing' OR 1=1 --"})
        self.assertEqual({row['item_id'] for row in result},{'A-W01','A-W04'})
