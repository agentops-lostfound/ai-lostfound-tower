"""운영 DB/인증 읽기 연결의 권한·HTTP·SQL 경계. 실제 서버/개인정보를 사용하지 않는다."""
from dataclasses import replace
import json
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.chat_api import add_chat_routes, build_chatbot_from_env
from agents.chat_find_auth import (
    FindSession, FindSessionAuth, FindAuthenticationRequired, FindAuthenticationUnavailable, PERMISSIONS,
)
from agents.chat_operations import Owner, OperationNotFound, binding_digest, owner_scope
from agents.chat_postgres_access import (
    PostgresFindSessions, PostgresOperationResults, PostgresAccessUnavailable,
    SQL_FIND_SESSION, SQL_OPERATION_RECEIPT, find_access_from_env,
)
from agents.chat_search import PostgresItemSearch, SearchAgent, SQL_SEARCH


KEY = b'fictional-server-binding-key-32-bytes'
TOKEN = 'fictional-bearer-token'
OWNER = Owner('fictional-subject', 'fictional-auth-session')
OP_ID = 'op_' + 'a' * 32
CONTEXT = {'category': '지갑', 'color': '검정', 'lost_date': '2026-11-01',
           'lost_line': '1호선', 'lost_station': '서면역'}


class PgServer:
    """고정 SQL과 파라미터로 분기하는 연결 대역. 읽기 전용/격리/타임아웃 설정도 검증."""
    def __init__(self):
        self.sessions = {}
        self.receipts = {}
        self.calls, self.connections = [], []
        self.failure = None
        self.ambiguous = False
        self.item_reads = 0
        self.register(TOKEN, OWNER)

    def register(self, token, owner, *, expires=2000, verified=True, consented=True, revoked=False,
                 permissions=None):
        self.sessions[binding_digest(KEY, 'find-token-v1', token)] = [
            owner.subject, owner.auth_session, expires, verified, consented, revoked,
            list(permissions if permissions is not None else PERMISSIONS)]

    def connect(self, dsn, **kwargs):
        if self.failure:
            raise self.failure
        server = self
        class DB:
            read_only = False
            isolation_level = None
            def __enter__(self):
                server.connections.append(self)
                return self
            def __exit__(self, *args):
                return False
            def cursor(self):
                return Cursor(self)
        class Cursor:
            def __init__(self, db):
                self.db, self.rows = db, []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql, params=None):
                if not self.db.read_only or self.db.isolation_level is None:
                    raise AssertionError('query outside configured read-only transaction')
                server.calls.append((sql, params))
                if sql == "SET LOCAL statement_timeout = '3000ms'":
                    self.rows = []
                elif sql == SQL_FIND_SESSION:
                    row = server.sessions.get(params[0])
                    self.rows = [row] if row is not None else []
                elif sql == SQL_OPERATION_RECEIPT:
                    row = server.receipts.get(params)
                    self.rows = [row] if row is not None else []
                elif sql == SQL_SEARCH:
                    server.item_reads += 1
                    self.rows = [('A-20261111-0001', '지갑', '검정', '본센터 보관')]
                else:
                    raise AssertionError('unexpected SQL')
            def fetchall(self):
                return self.rows * 2 if server.ambiguous else self.rows
        return DB()


class Bot:
    def __init__(self, search):
        self.search, self.calls = search, []
        self.guidance = SimpleNamespace(record_suggestion=lambda *args: None)
        self.rag = SimpleNamespace(model=None)
    def ask(self, question, token=None, context=None, history=None, staff=False,
            session_id=None, channel='web', intake_action=None):
        self.calls.append({'session_id': session_id, 'intake_action': intake_action})
        return self.search.ask(question, token, context)


class FindAccessTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict('os.environ', {'LF_LANGFUSE': '0', 'LF_CHAT_RAG_MODEL': '',
                 'LF_CHAT_SESSION_DATABASE_URL': '', 'LF_CHAT_OPERATION_DATABASE_URL': '',
                 'LF_CHAT_BINDING_KEY_HEX': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.pg = PgServer()
        self.sessions = PostgresFindSessions('fictional-auth-dsn', connect=self.pg.connect)
        self.auth = FindSessionAuth(self.sessions.lookup, KEY, clock=lambda: 1000)
        self.results = PostgresOperationResults('fictional-operation-dsn', KEY, connect=self.pg.connect)
        self.search = SearchAgent(PostgresItemSearch('fictional-item-dsn', connect=self.pg.connect))
        self.bot = Bot(self.search)
        app = FastAPI()
        add_chat_routes(app, self.bot, find_auth=self.auth, operation_results=self.results)
        self.client = TestClient(app)
        self.headers = {'Authorization': 'Bearer ' + TOKEN}

    def question(self, headers=None, **extra):
        return self.client.post('/chat/questions', headers=self.headers if headers is None else headers,
            json={'question': '검정 지갑 찾아줘', 'search_context': CONTEXT,
                  'session_id': 'browser-conversation', **extra})

    def add_receipt(self, state='completed', result=None, owner=OWNER):
        scope = owner_scope(KEY, owner)
        row = (OP_ID, scope, 'found', 'b' * 64, state,
               {'item_id': 'A-20261111-0001'} if result is None else result)
        self.pg.receipts[(OP_ID, scope)] = row
        return row

    def test_verified_session_enables_existing_parameterized_postgres_search(self):
        response = self.question()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'items_found')
        self.assertEqual(self.pg.item_reads, 1)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('A-20261111-0001', response.text)
        self.assertNotIn(TOKEN, repr(self.pg.calls))
        self.assertNotIn(OWNER.subject, str(self.bot.calls))
        self.assertNotEqual(self.bot.calls[-1]['session_id'], 'browser-conversation')
        self.assertEqual(len(self.bot.calls[-1]['session_id']), 64)

    def test_missing_forged_and_client_claimed_identity_cannot_reach_bot_or_item_db(self):
        for headers in ({}, {'Authorization': 'Bearer forged'}, {'Authorization': 'Basic forged'}):
            response = self.question(headers=headers, id_verified=True, consent=True,
                                     subject_id=OWNER.subject, auth_session_id=OWNER.auth_session)
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.bot.calls, [])
        self.assertEqual(self.pg.item_reads, 0)

    def test_expiry_revocation_consent_and_verification_checked_every_request(self):
        self.assertEqual(self.question().status_code, 200)
        for overrides in ({'expires': 999}, {'expires': 1000}, {'revoked': True},
                          {'verified': False}, {'consented': False}, {'verified': 1}):
            self.pg.register(TOKEN, OWNER, **overrides)
            self.assertEqual(self.question().status_code, 401)
        self.assertEqual(self.pg.item_reads, 1)

    def test_permission_for_chat_does_not_grant_search_or_operation_read(self):
        self.pg.register(TOKEN, OWNER, permissions=['chat:use'])
        response = self.question()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'authentication_required')
        self.assertEqual(self.pg.item_reads, 0)
        self.assertEqual(self.client.get('/chat/operations/' + OP_ID, headers=self.headers).status_code, 401)

    def test_same_browser_session_is_isolated_by_user_and_auth_session(self):
        self.question()
        first = self.bot.calls[-1]['session_id']
        for owner in (Owner('another-subject', OWNER.auth_session), Owner(OWNER.subject, 'other-session')):
            self.pg.register('other-token', owner)
            self.question(headers={'Authorization': 'Bearer other-token'})
            self.assertNotEqual(self.bot.calls[-1]['session_id'], first)
        self.question()
        self.assertEqual(self.bot.calls[-1]['session_id'], first)

    def test_stream_uses_identical_auth_and_conversation_binding(self):
        self.question()
        expected_sid = self.bot.calls[-1]['session_id']
        response = self.question(stream=True)
        self.assertEqual(response.status_code, 200)
        final = json.loads(response.text.strip().splitlines()[-1])
        self.assertTrue(final['done'])
        self.assertEqual(final['status'], 'items_found')
        self.assertEqual(self.bot.calls[-1]['session_id'], expected_sid)
        self.assertNotIn(TOKEN, response.text)
        self.assertEqual(self.question(headers={}, stream=True).status_code, 401)

    def test_owner_only_operation_lookup_returns_minimal_result_without_execution(self):
        self.add_receipt()
        response = self.client.get('/chat/operations/' + OP_ID, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'operation_id', 'kind', 'state', 'result', 'retry_allowed'})
        self.assertFalse(response.json()['retry_allowed'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        for sensitive in (OWNER.subject, OWNER.auth_session, TOKEN, 'owner_scope', 'request_hash'):
            self.assertNotIn(sensitive, response.text)
        self.assertTrue(all(sql.lstrip().startswith(('SELECT', 'SET LOCAL')) for sql, _ in self.pg.calls))

    def test_other_user_and_other_session_see_same_404_as_missing_work(self):
        self.add_receipt()
        for owner in (Owner('another-user', OWNER.auth_session), Owner(OWNER.subject, 'other-session')):
            self.pg.register('other-token', owner)
            response = self.client.get('/chat/operations/' + OP_ID,
                                       headers={'Authorization': 'Bearer other-token'})
            missing = self.client.get('/chat/operations/op_' + 'f' * 32,
                                      headers={'Authorization': 'Bearer other-token'})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), missing.json())

    def test_operation_result_rechecks_revocation_after_db_read(self):
        self.add_receipt()
        real_get = self.results.get
        def read_then_revoke(owner, op_id):
            result = real_get(owner, op_id)
            self.pg.register(TOKEN, OWNER, revoked=True)
            return result
        with patch.object(self.results, 'get', side_effect=read_then_revoke):
            response = self.client.get('/chat/operations/' + OP_ID, headers=self.headers)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn('item_id', response.text)

    def test_nonterminal_and_rejected_states_never_show_success_ids(self):
        for state in ('prepared', 'running', 'uncertain', 'rejected'):
            self.add_receipt(state, {})
            response = self.client.get('/chat/operations/' + OP_ID, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['state'], state)
            self.assertEqual(response.json()['result'], {})
            self.add_receipt(state, {'item_id': 'A-20261111-0001'})
            self.assertEqual(self.client.get('/chat/operations/' + OP_ID, headers=self.headers).status_code, 503)

    def test_bad_db_receipt_is_not_accepted_as_success(self):
        row = self.add_receipt()
        for index, value in ((0, 'op_' + 'c' * 32), (1, 'wrong-owner'), (2, 'unknown-kind'),
                             (3, 'bad-hash'), (4, 'unknown-state'), (5, {'item_id': True}),
                             (5, {'item_id': ' '}), (5, {'item_id': 'A-1', 'private': 'secret'})):
            bad = list(row)
            bad[index] = value
            self.pg.receipts[(OP_ID, owner_scope(KEY, OWNER))] = tuple(bad)
            self.assertEqual(self.client.get('/chat/operations/' + OP_ID, headers=self.headers).status_code, 503)

    def test_db_error_is_sanitized_and_never_falls_back_to_demo(self):
        self.pg.failure = RuntimeError('synthetic-password-and-dsn')
        response = self.question()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('synthetic-password-and-dsn', response.text)
        self.assertEqual(self.bot.calls, [])
        self.assertEqual(self.pg.item_reads, 0)
        self.assertNotIn('fictional-auth-dsn', repr(self.sessions))
        self.assertNotIn(KEY.decode(), repr(self.auth))

    def test_result_db_failure_does_not_expose_exception_text(self):
        with patch.object(self.results, '_connect', side_effect=RuntimeError('private-connection-error')):
            response = self.client.get('/chat/operations/' + OP_ID, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-connection-error', response.text)

    def test_missing_verifier_keeps_existing_real_search_locked(self):
        agent = SearchAgent(self.search.database)
        self.assertEqual(agent.ask('검정 지갑 찾아줘', TOKEN, CONTEXT)['status'], 'authentication_required')
        self.assertEqual(self.pg.item_reads, 0)
        app = FastAPI()
        add_chat_routes(app, Bot(agent))
        self.assertEqual(TestClient(app).get('/chat/operations/' + OP_ID, headers=self.headers).status_code, 404)

    def test_invalid_ids_do_not_become_sql(self):
        before = len(self.pg.calls)
        with self.assertRaises(OperationNotFound):
            self.results.get(OWNER, "op_' OR true --")
        self.assertEqual(len(self.pg.calls), before)
        self.assertIsNone(self.sessions.lookup("' OR true --"))

    def test_configuration_requires_explicit_session_db_and_persistent_key(self):
        self.assertEqual(find_access_from_env({}), (None, None))
        for env in ({'LF_CHAT_SESSION_DATABASE_URL': 'fake'}, {'LF_CHAT_BINDING_KEY_HEX': 'ab' * 32},
                    {'LF_CHAT_OPERATION_DATABASE_URL': 'fake'},
                    {'LF_CHAT_SESSION_DATABASE_URL': 'fake', 'LF_CHAT_BINDING_KEY_HEX': 'ab' * 31}):
            with self.assertRaises(ValueError):
                find_access_from_env(env)
        auth, result = find_access_from_env({'LF_CHAT_SESSION_DATABASE_URL': 'fake-session',
            'LF_CHAT_BINDING_KEY_HEX': KEY.hex(), 'LF_CHAT_OPERATION_DATABASE_URL': 'fake-result'})
        self.assertIsInstance(auth, FindSessionAuth)
        self.assertIsInstance(result, PostgresOperationResults)

    def test_untrusted_lookup_claims_and_invalid_expiration_are_rejected(self):
        session = self.auth.require(TOKEN)
        for returned in (True, {'id_verified': True}, replace(session, expires_at=math.nan),
                         replace(session, expires_at=10 ** 1000), replace(session, expires_at=True),
                         replace(session, consented=1), replace(session, permissions={'chat:use'})):
            auth = FindSessionAuth(lambda _: returned, KEY, clock=lambda: 1000)
            with self.assertRaises(FindAuthenticationRequired):
                auth.require(TOKEN)

    def test_server_factory_passes_verifier_to_existing_search_agent(self):
        bot = build_chatbot_from_env(database=self.search.database, find_auth=self.auth)
        self.assertTrue(bot.search._authorized(TOKEN))
        self.pg.register(TOKEN, OWNER, revoked=True)
        self.assertFalse(bot.search._authorized(TOKEN))

    def test_operation_scope_matches_previously_committed_journal_contract(self):
        # 소유자 결합 규칙을 바꿔 과거 작업 ID에 접근하지 못하게 되는 회귀 방지.
        expected = binding_digest(KEY, 'owner', [OWNER.subject, OWNER.auth_session])
        self.assertEqual(owner_scope(KEY, OWNER), expected)

    def test_staff_conversation_cannot_select_user_conversation_by_body_id(self):
        session = self.auth.require(TOKEN)
        user_sid = self.auth.conversation_id(session, 'browser-conversation')
        self.assertNotEqual(self.auth.staff_conversation_id(user_sid), user_sid)

    def test_admin_headers_and_cookie_do_not_grant_user_operation_access(self):
        response = self.client.get('/chat/operations/' + OP_ID,
            headers={'X-Admin-Key': 'fictional-admin-key', 'Cookie': 'lf_admin=fictional-cookie'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.pg.calls, [])

    def test_session_lookup_never_caches_positive_authorization(self):
        self.assertTrue(self.auth.authorize(TOKEN))
        self.pg.register(TOKEN, OWNER, revoked=True)
        self.assertFalse(self.auth.authorize(TOKEN))
        self.assertEqual(sum(sql == SQL_FIND_SESSION for sql, _ in self.pg.calls), 2)

    def test_ambiguous_authoritative_rows_fail_closed(self):
        self.pg.ambiguous = True
        with self.assertRaises(FindAuthenticationUnavailable):
            self.auth.require(TOKEN)
        self.pg.ambiguous = False
        with patch.object(self.sessions, '_query', return_value=[*self.pg.sessions.values()][0][:-1] + [None]):
            with self.assertRaises(FindAuthenticationUnavailable):
                self.auth.require(TOKEN)

    def test_operation_reader_cannot_be_enabled_without_user_authentication(self):
        with self.assertRaises(ValueError):
            add_chat_routes(FastAPI(), self.bot, operation_results=self.results)

    def test_tower_app_forwards_user_auth_and_operation_reader(self):
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        service = build_sim_service({'TOWER_SIM_SEED': 'full', 'TOWER_SIM_SPEED': '0',
                                    'TOWER_GPU_LEASE': '0', 'TOWER_SEND': '0', 'TOWER_AGENT_TALK': '0'})
        self.add_receipt()
        app = build_app(service=service, chatbot=self.bot, find_auth=self.auth, operation_results=self.results)
        client = TestClient(app)
        self.assertEqual(client.get('/chat/operations/' + OP_ID, headers=self.headers).status_code, 200)
        self.assertEqual(client.post('/chat/questions', json={'question': '분실물 안내'}).status_code, 401)

    def test_standalone_lost_app_uses_the_same_auth_boundary(self):
        from agents.lost_api import create_app
        self.add_receipt()
        app = create_app(chatbot=self.bot, find_auth=self.auth, operation_results=self.results)
        client = TestClient(app, base_url='http://127.0.0.1:8111')
        self.assertEqual(client.get('/chat/operations/' + OP_ID, headers=self.headers).status_code, 200)
        self.assertEqual(client.post('/chat/questions', json={'question': '분실물 안내'}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
