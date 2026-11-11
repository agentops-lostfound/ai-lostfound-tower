import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from agents.candidate_registry import CandidateRegistry
from agents.chatbot import Chatbot
from agents.chat_search import DemoItemDatabase, PostgresItemSearch, SearchAgent, SQL_SEARCH
from agents.guidance import Guidance
from agents.lost_api import create_app
from agents.lost_input import DescriptionService, KST, text_features
from agents.search_context import search_context

CONTEXT = {'category': '립밤', 'color': '검정', 'lost_date': '2026-11-01', 'lost_line': '1호선', 'lost_station': '중앙역'}


class SearchHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = DemoItemDatabase(Path(self.tmp.name) / 'demo.sqlite3', today=date(2026, 11, 4))
        self.agent = SearchAgent(self.db)

    def insert(self, *rows):
        with closing(sqlite3.connect(self.db.path)) as db, db:
            db.executemany('INSERT INTO chat_demo_catalog VALUES (?,?,?,?,?,?,?)', rows)

    def test_confirmed_context_can_search_without_retyping_description(self):
        result = self.agent.ask('확인한 설명으로 찾아줘', context=CONTEXT)
        self.assertEqual(result['status'], 'items_found')
        self.assertEqual(result['search_filter']['lost_station'], '중앙')
        self.assertEqual(self.agent.resolve_candidate(result['search_result_id'], 1, None), 'DEMO-001')

    def test_api_cards_never_expose_receipt_id_station_status_score_or_private_fields(self):
        guide = Guidance(); bot = Chatbot(guide, search=self.agent)
        client = TestClient(create_app(DescriptionService(), guide, bot), base_url='http://127.0.0.1')
        response = client.post('/chat/questions', json={'question': '확인한 설명으로 찾아줘', 'search_context': CONTEXT})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(set(result['candidates'][0]), {'candidate_no', 'category', 'color'})
        self.assertNotIn('DEMO-001', response.text)
        self.assertNotIn('본센터 보관', response.text)
        self.assertNotIn('score', result['candidates'][0])
        self.assertNotIn('station', result['candidates'][0])

    def test_station_has_priority_without_filling_cards_from_other_stations(self):
        self.insert(('DEMO-007','립밤','검정','본센터 보관','1호선','초량','2026-11-04'),
                    ('DEMO-008','립밤','검정','본센터 보관','1호선','부산','2026-11-04'))
        result = self.agent.ask('찾아줘', context=CONTEXT)
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(self.agent.resolve_candidate(result['search_result_id'],1,None), 'DEMO-001')

    def test_station_without_results_falls_back_only_to_same_line(self):
        self.insert(('DEMO-007','립밤','검정','본센터 보관','2호선','센텀','2026-11-04'))
        result = self.agent.ask('찾아줘', context={**CONTEXT,'lost_station':'광안역'})
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(self.agent.resolve_candidate(result['search_result_id'],1,None), 'DEMO-001')

    def test_future_reception_can_match_but_reception_before_loss_is_excluded(self):
        result = self.agent.ask('핸드크림 찾아줘', context={'lost_date':'2026-11-03'})
        self.assertEqual(result['status'], 'items_not_found')
        result = self.agent.ask('립밤 찾아줘', context={'lost_date':'2026-11-03'})
        self.assertEqual(result['status'], 'items_found')

    def test_new_category_cannot_inherit_old_category_color_or_location(self):
        context, warnings = search_context('휴대폰 찾아줘', CONTEXT)
        self.assertEqual(context, {'category':'모형폰'})
        self.assertFalse(warnings)

    def test_new_explicit_color_overrides_reviewed_color(self):
        context, _ = search_context('파란 립밤 찾아줘', CONTEXT)
        self.assertEqual(context['color'], '파랑')
        self.assertEqual(context['lost_station'], '중앙')

    def test_question_line_without_spacing_and_station_suffix_normalize(self):
        context, _ = search_context('2026-11-01 1호선중앙역 검정 립밤 찾아줘')
        self.assertEqual(context['lost_station'], '중앙')
        self.assertEqual(context['lost_line'], '1호선')

    def test_ambiguous_question_does_not_silently_use_old_context(self):
        self.assertEqual(self.agent.ask('립밤 말고 USB 찾아줘', context=CONTEXT)['status'], 'search_needs_details')

    def test_future_date_invalid_line_and_private_identity_context_are_rejected(self):
        future = (datetime.now(KST).date()+timedelta(days=1)).isoformat()
        for context in [{'lost_date':future}, {'lost_line':'2; DROP'}, {'id_verified':True},
                        {'mark':'private'}, {'lost_station':'010-1234-5678'}, []]:
            with self.subTest(context=context), self.assertRaises(ValueError):
                self.agent.ask('립밤 찾아줘', context=context)

    def test_pink_alias_uses_latest_team_color_contract(self):
        self.assertEqual(text_features('핑크 립밤')[0]['color'], '분홍')

    def test_real_search_requires_loss_metadata_even_after_trusted_verification(self):
        db = MagicMock(mode='postgres')
        agent = SearchAgent(db, authorize=lambda token: token=='valid')
        self.assertEqual(agent.ask('립밤 찾아줘','valid')['status'], 'search_needs_details')
        db.search.assert_not_called()

    def test_empty_bearer_cannot_be_authorized_by_a_permissive_adapter(self):
        db = MagicMock(mode='postgres')
        agent = SearchAgent(db, authorize=lambda _:True)
        self.assertEqual(agent.ask('립밤 찾아줘',None,CONTEXT)['status'], 'authentication_required')
        db.search.assert_not_called()

    def test_custom_database_extra_fields_and_duplicate_items_do_not_reach_api(self):
        db = MagicMock(mode='postgres')
        row = {'item_id':'A-W01','category':'립밤','color':'검정','status':'본센터 보관',
               'station':'secret-station','mark':'secret-answer','score':0.98}
        db.search.return_value = [row, dict(row)]
        agent = SearchAgent(db, authorize=lambda token: token=='valid')
        result = agent.ask('찾아줘','valid',CONTEXT)
        self.assertEqual(len(result['candidates']),1)
        self.assertNotIn('A-W01',json.dumps(result))
        self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(agent.resolve_candidate(result['search_result_id'],1,'valid'),'A-W01')


class CandidateRegistryTests(unittest.TestCase):
    def test_result_is_owner_bound_expiring_and_revalidated_on_selection(self):
        clock = [0]; registry = CandidateRegistry(clock=lambda:clock[0])
        ref = registry.issue(['A-W01'],'owner-one')
        self.assertEqual(registry.resolve(ref,1,'owner-one'),'A-W01')
        for number, owner in [(1,'owner-two'),(0,'owner-one'),(True,'owner-one'),(4,'owner-one')]:
            with self.assertRaises(ValueError): registry.resolve(ref,number,owner)
        clock[0]=601
        with self.assertRaises(ValueError): registry.resolve(ref,1,'owner-one')

    def test_reference_does_not_store_plaintext_authentication_token(self):
        registry = CandidateRegistry(); registry.issue(['A-W01'],'synthetic-private-token')
        self.assertNotIn('synthetic-private-token',repr(registry._entries))

    def test_per_owner_limit_evicts_only_that_owners_old_reference(self):
        registry=CandidateRegistry(max_per_owner=1)
        old=registry.issue(['A-W01'],'one'); other=registry.issue(['A-W02'],'two')
        registry.issue(['A-W03'],'one')
        with self.assertRaises(ValueError): registry.resolve(old,1,'one')
        self.assertEqual(registry.resolve(other,1,'two'),'A-W02')

    def test_global_registry_capacity_is_bounded(self):
        registry=CandidateRegistry(max_entries=1)
        registry.issue(['A-W01'],'one')
        with self.assertRaises(RuntimeError): registry.issue(['A-W02'],'two')

    def test_revoked_trusted_session_cannot_resolve_an_existing_reference(self):
        db=MagicMock(mode='postgres'); db.search.return_value=[{'item_id':'A-W01','category':'립밤','color':'검정','status':'본센터 보관'}]
        allowed=[True]; agent=SearchAgent(db,authorize=lambda _:allowed[0])
        result=agent.ask('찾아줘','valid',CONTEXT)
        allowed[0]=False
        with self.assertRaises(ValueError): agent.resolve_candidate(result['search_result_id'],1,'valid')


class PostgresSearchFilterTests(unittest.TestCase):
    def db(self, replies):
        connection=MagicMock(); connection.__enter__.return_value=connection
        cursor=connection.cursor.return_value.__enter__.return_value; cursor.fetchall.side_effect=replies
        return PostgresItemSearch('synthetic-test',connect=MagicMock(return_value=connection)),cursor,connection

    def test_bound_station_line_and_korean_date_lower_boundary(self):
        db,cursor,connection=self.db([[('A-W01','립밤','검정','본센터 보관')]])
        db.search('립밤','검정',{**CONTEXT,'lost_station':'중앙'})
        sql,params=cursor.execute.call_args.args
        self.assertEqual(sql,SQL_SEARCH)
        self.assertEqual(params[4:8],('1호선','1호선','중앙','중앙'))
        self.assertEqual(params[8],datetime(2026,11,1,tzinfo=KST))
        self.assertTrue(connection.read_only)

    def test_fallback_changes_station_only_and_preserves_date_and_line(self):
        db,cursor,_=self.db([[],[('A-W01','립밤','검정','본센터 보관')]])
        result=db.search('립밤','검정',{**CONTEXT,'lost_station':'광안'})
        queries=[c.args for c in cursor.execute.call_args_list if c.args[0]==SQL_SEARCH]
        self.assertEqual(len(queries),2)
        self.assertEqual(queries[0][1][6:8],('광안','광안'))
        self.assertEqual(queries[1][1][6:8],(None,None))
        self.assertEqual(queries[0][1][8:],queries[1][1][8:])
        self.assertEqual(queries[1][1][4:6],('1호선','1호선'))
        self.assertEqual(result[0]['item_id'],'A-W01')
