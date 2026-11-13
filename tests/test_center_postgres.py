"""Opt-in integration tests: ONLY a disposable database named lf_support_test."""
import os
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from center.collections import CollectionStore, CollectionError
from center.statistics import Statistics
from center.places import Places
from discord_ops.reporter import Reporter
from agents.intake import PostgresIntakeStore, parse_intake
from agents.chat_search import PostgresItemSearch, SearchAgent
from agents.lost_input import KST


@unittest.skipUnless(os.environ.get("LF_SUPPORT_TEST_DSN"), "disposable PostgreSQL not configured")
class PostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.connect = staticmethod(lambda: psycopg.connect(os.environ["LF_SUPPORT_TEST_DSN"]))
        with cls.connect() as conn:
            if conn.info.dbname != "lf_support_test":
                raise RuntimeError("Integration tests require disposable database lf_support_test")
            root = Path(__file__).resolve().parents[1]
            conn.execute((root / "center/schema.sql").read_text(encoding="utf-8"))
            for path in sorted((root / "center/migrations").glob("*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))
            # Team main keeps LF-9's unapproved schema in pending/. Opt in only
            # here, after the disposable database-name guard; never promote it.
            pending = root / 'center/migrations/pending/006_collection_alerts_1104.sql'
            if pending.is_file():
                conn.execute(pending.read_text(encoding='utf-8'))

    def setUp(self):
        with self.connect() as conn:
            conn.execute("TRUNCATE machine CASCADE")
            conn.execute("TRUNCATE place CASCADE")
            conn.execute("INSERT INTO machine(machine_id,kind,line,station) VALUES('KIOSK-A','kiosk','1호선','중앙'),('KIOSK-C','kiosk','1호선','초량')")
            for iid in ("A-W01", "A-W02"):
                conn.execute("INSERT INTO item(item_id,machine_id,place_text,category,received_at) VALUES(%s,'KIOSK-A','시험 장소','USB','2026-11-04 00:30+09')", (iid,))
        self.store = CollectionStore(self.connect)

    def test_concurrent_retry_and_partial_then_complete_arrival(self):
        def pickup(_):
            return self.store.pickup("KIOSK-A", ["A-W01", "A-W02"], "same-request-001")
        with ThreadPoolExecutor(2) as executor:
            first, retry = list(executor.map(pickup, range(2)))
        self.assertEqual(first["collection_id"], retry["collection_id"])
        cid = first["collection_id"]
        partial = self.store.arrive(cid, ["A-W01"])
        self.assertEqual(partial["missing_item_ids"], ["A-W02"])
        self.assertIsNone(partial["arrived_at"])
        self.store.arrive(cid, ["A-W01"])
        reporter = Reporter(dry_run=True)
        self.assertEqual(self.store.dispatch(reporter), 0)
        self.assertEqual(len(reporter.messages), 1)
        complete = self.store.arrive(cid, ["A-W02"])
        self.assertIsNotNone(complete["arrived_at"])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM collection").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM item_status_log").fetchone()[0], 4)
            self.assertEqual(conn.execute("SELECT count(*) FROM item WHERE status='본센터 보관'").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM collection_alert WHERE resolved_at IS NULL").fetchone()[0], 0)

    def test_invalid_pickup_rolls_back_entire_batch(self):
        with self.assertRaises(CollectionError):
            self.store.pickup("KIOSK-A", ["A-W01", "A-W99"], "rollback-request")
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM collection").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT status FROM item WHERE item_id='A-W01'").fetchone()[0], "등록기계 보관")

    def test_zero_arrivals_and_explicit_deadline(self):
        cid = self.store.pickup("KIOSK-A", ["A-W01", "A-W02"], "missing-request")["collection_id"]
        self.assertEqual(len(self.store.arrive(cid, [])["missing_item_ids"]), 2)
        self.assertEqual(self.store.overdue(datetime(2100, 1, 1, tzinfo=timezone.utc)), 0)

    def test_statistics_counts_and_role_denies_private_tables_and_writes(self):
        result = Statistics(self.connect).ask("오늘 등록기계 A에 들어온 USB 몇 개?", datetime(2026, 11, 4, 3, tzinfo=timezone.utc))
        self.assertEqual(result["count"], 2)
        import psycopg
        for query in ("SELECT * FROM claim", "SELECT * FROM finder_contact", "UPDATE item SET category='립밤'"):
            with self.connect() as conn:
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute("SET LOCAL ROLE lf_stats_reader")
                with self.assertRaises(psycopg.Error):
                    conn.execute(query)

    def test_place_upsert_and_paging(self):
        store = Places(self.connect)
        for n in range(7):
            store.put("1호선", "중앙", f"장소{n}")
        one = store.put("1호선", "중앙", "장소0")
        self.assertEqual(one, store.put("1호선", "중앙", "장소0"))
        page = store.recommend("KIOSK-A")
        self.assertEqual(len(page["places"]), 5)
        self.assertEqual(len(store.recommend("KIOSK-A", page["next_offset"])["places"]), 2)

    def test_place_station_aliases_and_concurrent_duplicates_share_a_single_id(self):
        store = Places(self.connect)
        def put(index):
            return store.put('１호선', ' 중앙역 ' if index % 2 else '중앙', ' 합성 새 장소 ')
        with ThreadPoolExecutor(4) as executor:
            ids = list(executor.map(put, range(8)))
        self.assertTrue(all(row == ids[0] for row in ids))
        self.assertEqual(store.recommend('KIOSK-A')['places'][0]['place_id'], ids[0]['place_id'])
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM place').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT station FROM place').fetchone()[0], '중앙')

    def test_place_recommendations_scope_order_paging_and_empty_results(self):
        store = Places(self.connect)
        ids = [store.put('1호선', '중앙', f'합성 장소{i}')['place_id'] for i in range(11)]
        other = store.put('1호선', '초량', '다른 역 장소')['place_id']
        with self.connect() as conn:
            conn.execute('UPDATE place SET use_count=10 WHERE place_id=%s', (ids[-1],))
        pages = [store.recommend('KIOSK-A', offset) for offset in (0, 5, 10)]
        all_ids = [p['place_id'] for page in pages for p in page['places']]
        self.assertEqual((len(all_ids), len(set(all_ids))), (11, 11))
        self.assertEqual(all_ids[0], ids[-1])
        self.assertNotIn(other, all_ids)
        self.assertEqual([page['next_offset'] for page in pages], [5, 10, None])
        self.assertEqual(store.recommend('KIOSK-A', 10000), {'places': [], 'next_offset': None})
        with self.connect() as conn:
            conn.execute("INSERT INTO machine(machine_id,kind,line,station) VALUES('EMPTY','kiosk','2호선','합성빈역')")
        self.assertEqual(store.recommend('EMPTY'), {'places': [], 'next_offset': None})
        for machine in ('MISSING', 'CENTER'):
            with self.assertRaises(ValueError):
                store.recommend(machine)

    def test_places_reject_unmapped_scopes_and_ambiguous_machine_spellings_without_writes(self):
        store = Places(self.connect)
        with self.assertRaises(ValueError):
            store.put('2호선', '중앙', '등록기계 없는 역')
        with self.connect() as conn:
            conn.execute("INSERT INTO machine(machine_id,kind,line,station) VALUES('ALIAS','kiosk','1호선','중앙역'),('NO-SCOPE','kiosk',NULL,NULL)")
        with self.assertRaises(ValueError):
            store.put('1호선', '중앙', '모호한 역')
        with self.assertRaises(ValueError):
            store.recommend('NO-SCOPE')
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM place').fetchone()[0], 0)

    def test_place_recommendation_is_usable_by_existing_intake(self):
        store = Places(self.connect)
        added = store.put('1호선', '초량역', '합성 승강장')
        place = store.recommend('KIOSK-C')['places'][0]
        self.assertEqual(place['place_id'], added['place_id'])
        intake = PostgresIntakeStore(os.environ['LF_SUPPORT_TEST_DSN'])
        item = intake.create(parse_intake({'machine_id': 'KIOSK-C', 'place_id': place['place_id'], 'place_text': place['label']}))
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT place_id FROM item WHERE item_id=%s', (item['item_id'],)).fetchone()[0], place['place_id'])
        self.assertEqual(store.recommend('KIOSK-A')['places'], [])

    def receive_lipbalms(self):
        dsn = os.environ['LF_SUPPORT_TEST_DSN']
        intake = PostgresIntakeStore(dsn)
        ids = []
        for _ in range(2):
            row = intake.create(parse_intake({'machine_id': 'KIOSK-A', 'place_text': '가상 통합 시험 장소'}))
            ids.append(row['item_id'])
            self.assertTrue(intake.set_features(row['item_id'], {'category': '립밤', 'color': '검정',
                'shape': 'rectangular', 'mark': '합성 비공개 정답'}))
        received = datetime.fromisoformat(row['received_at']).astimezone(KST)
        context = {'lost_date': (received.date()-timedelta(days=1)).isoformat(),
                   'lost_line': '1호선', 'lost_station': '중앙역'}
        agent = SearchAgent(PostgresItemSearch(dsn), authorize=lambda token: token == 'synthetic-verified-session')
        return ids, received, context, agent

    def assert_search_and_count(self, agent, context, expected_ids, received):
        token = 'synthetic-verified-session'
        result = agent.ask('검정 립밤 찾아줘', token, context)
        self.assertEqual(result['status'], 'items_found' if expected_ids else 'items_not_found')
        actual = {agent.resolve_candidate(result['search_result_id'], number, token)
                  for number in range(1, len(result['candidates'])+1)}
        self.assertEqual(actual, set(expected_ids))
        self.assertNotIn('합성 비공개 정답', str(result))
        for item_id in expected_ids:
            self.assertNotIn(item_id, str(result))
        count = Statistics(self.connect).ask(f'{received.date()} 등록기계 A에 들어온 립밤 몇 개?', received)
        self.assertEqual(count['count'], 2)

    def test_intake_pickup_partial_arrival_search_and_statistics_share_one_database(self):
        ids, received, context, agent = self.receive_lipbalms()
        self.assert_search_and_count(agent, context, ids, received)
        first = self.store.pickup('KIOSK-A', ids, 'integrated-retry-001')
        retry = self.store.pickup('KIOSK-A', ids, 'integrated-retry-001')
        self.assertEqual(first['collection_id'], retry['collection_id'])
        self.assert_search_and_count(agent, context, [], received)
        cid = first['collection_id']
        partial = self.store.arrive(cid, [ids[0]])
        self.assertEqual(partial['missing_item_ids'], [ids[1]])
        self.assert_search_and_count(agent, context, [ids[0]], received)
        self.store.arrive(cid, [ids[0]])  # Replaying a saved arrival must not add history.
        self.store.arrive(cid, [ids[1]])
        self.assert_search_and_count(agent, context, ids, received)
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM collection').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM item_status_log WHERE item_id=ANY(%s)', (ids,)).fetchone()[0], 6)
            self.assertEqual(conn.execute('SELECT count(*) FROM collection_alert WHERE resolved_at IS NULL').fetchone()[0], 0)

    def test_failed_collection_keeps_search_and_statistics_and_does_not_grant_identity(self):
        ids, received, context, agent = self.receive_lipbalms()
        with self.assertRaises(CollectionError):
            self.store.pickup('KIOSK-C', ids, 'integrated-wrong-machine')
        with self.assertRaises(CollectionError):
            self.store.pickup('KIOSK-A', [ids[0], 'A-W99'], 'integrated-missing-item')
        self.assert_search_and_count(agent, context, ids, received)
        from unittest.mock import patch
        with patch.object(agent.database, 'search', wraps=agent.database.search) as query:
            for token in (None, 'synthetic-forged-session'):
                result = agent.ask('검정 립밤 찾아줘', token, context)
                self.assertEqual(result['status'], 'authentication_required')
                self.assertFalse(result['item_search_performed'])
            query.assert_not_called()
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM collection').fetchone()[0], 0)

    def test_confirmed_http_search_scene_receipts_and_collection_lifecycle_together(self):
        from fastapi.testclient import TestClient
        from agents.chatbot import Chatbot
        from agents.guidance import Guidance
        from agents.lost_api import create_app
        from agents.lost_input import DescriptionService
        from agents.chat_search import SEARCH_STATUSES
        from agents.scene_bindings import bind_scene, scene_digest
        from tools.check_chat_matching import synthetic_scene
        ids, received, context, agent = self.receive_lipbalms()
        guide = Guidance()
        bot = Chatbot(guide, search=agent)
        with TestClient(create_app(DescriptionService(), guide, bot), base_url='http://127.0.0.1') as client:
            proposal = client.post('/descriptions/text', json={'text': '검정 립밤', **context}).json()
            confirmed = client.post('/descriptions/'+proposal['proposal_id']+'/confirm', json={'confirmed': True})
            self.assertEqual(confirmed.status_code, 200, confirmed.text)
            self.assertFalse(confirmed.json()['identity_verified'])
            handoff = {**context, **confirmed.json()['description']}
            def chat_count(expected, token='synthetic-verified-session'):
                response = client.post('/chat/questions', headers={'Authorization': 'Bearer '+token},
                    json={'question': '찾아줘', 'search_context': handoff})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                if token != 'synthetic-verified-session':
                    self.assertEqual(result['status'], 'authentication_required')
                self.assertEqual(len(result['candidates']), expected)
                self.assertFalse(result['reservation_created'])
                for iid in ids: self.assertNotIn(iid, str(result))
            def inspect_links(expected, phase):
                # A new synthetic capture is supplied explicitly for each phase.
                report = synthetic_scene()
                report['objects'] = report['objects'][:2]
                for obj in report['objects']:
                    obj['qwen']['features'].update(category='lip_balm', colors=['black'])
                manifest = {'capture_id': 'synthetic-phase-'+phase, 'captured_at': datetime.now(timezone.utc).isoformat(),
                    'report_sha256': scene_digest(report), 'bindings': [
                        {'vision_id': obj['id'], 'item_id': iid} for obj, iid in zip(report['objects'], ids)]}
                def inventory_check(iid):
                    with self.connect() as conn:
                        conn.read_only = True
                        row = conn.execute('SELECT status FROM item WHERE item_id=%s', (iid,)).fetchone()
                        return bool(row and row[0] in SEARCH_STATUSES)
                result = bot.inspect_inventory_matching('검정 립밤', bind_scene(report, manifest), inventory_check)
                self.assertIs(result['inventory_link_checked'], expected)
                self.assertFalse(result['robot_authorized'])
                self.assertFalse(result['identity_verified'])
                self.assertFalse(result['reservation_created'])
                for iid in ids: self.assertNotIn(iid, str(result))
            chat_count(0, 'synthetic-unverified')
            chat_count(2); inspect_links(True, 'received')
            first = self.store.pickup('KIOSK-A', ids, 'http-scene-collection-001')
            retry = self.store.pickup('KIOSK-A', ids, 'http-scene-collection-001')
            self.assertEqual(first['collection_id'], retry['collection_id'])
            chat_count(0); inspect_links(False, 'moving')
            cid = first['collection_id']
            self.store.arrive(cid, [ids[0]])
            chat_count(1); inspect_links(False, 'partial')
            self.store.arrive(cid, [ids[0]])
            self.store.arrive(cid, [ids[1]])
            chat_count(2); inspect_links(True, 'arrived')
            self.assert_search_and_count(agent, context, ids, received)
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM collection').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM item_status_log WHERE item_id=ANY(%s)', (ids,)).fetchone()[0], 6)
            self.assertEqual(conn.execute('SELECT count(*) FROM collection_alert WHERE resolved_at IS NULL').fetchone()[0], 0)

    def test_tower_admin_session_collection_dashboard_readiness_and_statistics(self):
        from fastapi.testclient import TestClient
        from agents.api import build_app
        from agents.admin_auth import AdminAuth
        from agents.service import TowerService, demo_backend_factory
        from center.readiness import check_readiness
        svc = TowerService(demo_backend_factory(), Reporter(dry_run=True))
        stores = {'collections': self.store, 'statistics': Statistics(self.connect), 'places': Places(self.connect)}
        app = build_app(svc, admin_auth=AdminAuth('synthetic-password', 'synthetic-secret'), center_services=stores)
        with TestClient(app, base_url='http://127.0.0.1') as client:
            self.assertEqual(client.get('/api/admin/center/dashboard').status_code, 401)
            self.assertEqual(client.post('/api/admin/login', json={'password': 'synthetic-password'}).status_code, 200)
            self.assertTrue(client.get('/api/admin/center/readiness').json()['ready'])
            self.assertEqual(client.get('/api/admin/center/dashboard').json()['mode'], 'postgres')
            payload = {'machine_id': 'KIOSK-A', 'item_ids': ['A-W01', 'A-W02'], 'request_id': 'tower-pickup-001'}
            cross = client.post('/api/admin/center/collections', json=payload, headers={'origin': 'https://example.com'})
            self.assertEqual(cross.status_code, 403)
            one = client.post('/api/admin/center/collections', json=payload)
            self.assertEqual(one.status_code, 200, one.text)
            cid = one.json()['collection_id']
            self.assertEqual(client.post('/api/admin/center/collections', json=payload).json()['collection_id'], cid)
            partial = client.post(f'/api/admin/center/collections/{cid}/arrivals', json={'item_ids': ['A-W01']}).json()
            self.assertEqual(partial['missing_item_ids'], ['A-W02'])
            self.assertEqual(len(client.get('/api/admin/center/dashboard').json()['alerts']), 1)
            done = client.post(f'/api/admin/center/collections/{cid}/arrivals', json={'item_ids': ['A-W02']}).json()
            self.assertTrue(done['arrived_at'])
            board = client.get('/api/admin/center/dashboard').json()
            self.assertEqual(board['alerts'], [])
            self.assertTrue(all(i['status'] == '본센터 보관' for i in board['items']))
            self.assertFalse(any(k in str(board) for k in ('name_masked', 'private_features', 'finder_contact')))
            count = client.post('/api/admin/center/statistics/questions', json={'question': '2026-11-04 전체 물건 접수 몇 건?'}).json()
            self.assertEqual(count['count'], 2)
            client.post('/api/admin/logout')
            self.assertEqual(client.get('/api/admin/center/dashboard').status_code, 401)
