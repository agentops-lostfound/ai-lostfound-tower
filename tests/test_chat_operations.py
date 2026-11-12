"""영속 작업 ID, 원자적 대역, 읽기 전용 복구와 권한 경계를 실제 파일 DB로 검증."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import multiprocessing
import os
import sqlite3
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from agents.chat_operations import (
    OperationJournal, Owner, OperationConflict, OperationNotFound, connection,
)
from intake_operation_fixture import SQLiteDesk


KEY = b'fictional-test-key-only-32-bytes-long'
OWNER = Owner('fictional-user', 'server-auth-session')
PAYLOAD = {'text': 'fictional item', 'identity': {'name_masked': '가*명'}}


def timeout():
    raise TimeoutError('sensitive error must not be stored')


def crash():
    raise SystemExit('simulated process termination')


def process_replay(args):
    journal_path, desk_path, operation_id = args
    journal = OperationJournal(journal_path, KEY)
    result = journal.dispatch(OWNER, operation_id, PAYLOAD, SQLiteDesk(desk_path))
    return result.state


def process_exit(journal_path, desk_path, operation_id, after_commit):
    def terminate():
        os._exit(19)
    desk = SQLiteDesk(desk_path, **{'after_commit' if after_commit else 'before_commit': terminate})
    OperationJournal(journal_path, KEY).dispatch(OWNER, operation_id, PAYLOAD, desk)


class OperationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal_path = Path(self.tmp.name) / 'journal.sqlite'
        self.desk_path = Path(self.tmp.name) / 'desk.sqlite'
        self.journal = OperationJournal(self.journal_path, KEY)
        self.desk = SQLiteDesk(self.desk_path)

    def prepare(self, kind='found', payload=PAYLOAD, proof='accepted-draft-1'):
        return self.journal.prepare(OWNER, proof, kind, payload)

    def dispatch(self, operation, payload=PAYLOAD, desk=None):
        return self.journal.dispatch(OWNER, operation.operation_id, payload, desk or self.desk)

    def recover(self, operation, desk=None):
        return self.journal.recover(OWNER, operation.operation_id, desk or self.desk)

    def test_id_is_durable_before_any_business_write(self):
        operation = self.prepare()
        self.assertEqual(operation.state, 'prepared')
        restarted = OperationJournal(self.journal_path, KEY)
        self.assertEqual(restarted.get(OWNER, operation.operation_id), operation)
        self.assertEqual(self.desk.effects(), 0)
        self.assertEqual(self.recover(operation), operation)
        self.assertEqual(self.desk.lookup_calls, 0)

    def test_same_accepted_confirmation_reuses_id_after_restart(self):
        operation = self.prepare()
        restarted = OperationJournal(self.journal_path, KEY)
        self.assertEqual(restarted.prepare(OWNER, 'accepted-draft-1', 'found', PAYLOAD), operation)
        changed = {'text': 'different item'}
        with self.assertRaises(OperationConflict):
            self.prepare(payload=changed)
        with self.assertRaises(OperationConflict):
            self.prepare(kind='lost')

    def test_canonical_field_order_and_separate_confirmation(self):
        operation = self.prepare()
        reordered = {'identity': {'name_masked': '가*명'}, 'text': 'fictional item'}
        self.assertEqual(self.prepare(payload=reordered), operation)
        self.assertNotEqual(self.prepare(proof='accepted-draft-2').operation_id, operation.operation_id)

    def test_four_write_kinds_and_repeated_dispatch(self):
        for kind in ('found', 'lost', 'answer', 'cancel_claim'):
            with self.subTest(kind=kind):
                operation = self.prepare(kind, proof=kind)
                result = self.dispatch(operation)
                self.assertEqual(result.state, 'completed')
                for _ in range(3):
                    self.assertEqual(self.dispatch(operation), result)
        self.assertEqual(self.desk.effects(), 4)
        self.assertEqual(self.desk.execute_calls, 4)

    def test_lost_pending_and_waiting_are_completed_commands_not_final_handover(self):
        for flag, key in (('quiz', 'pending_id'), ('waiting', 'wait_id')):
            payload = {flag: True}
            operation = self.prepare('lost', payload, flag)
            result = self.dispatch(operation, payload)
            self.assertEqual(result.state, 'completed')
            self.assertIn(key, result.result)

    def test_response_loss_recovers_original_receipt_for_every_kind(self):
        for kind in ('found', 'lost', 'answer', 'cancel_claim'):
            with self.subTest(kind=kind):
                desk = SQLiteDesk(self.desk_path, after_commit=timeout)
                operation = self.prepare(kind, proof=kind)
                self.assertEqual(self.dispatch(operation, desk=desk).state, 'uncertain')
                restarted = OperationJournal(self.journal_path, KEY)
                result = restarted.recover(OWNER, operation.operation_id, SQLiteDesk(self.desk_path))
                self.assertEqual(result.state, 'completed')
                self.assertEqual(result.operation_id, operation.operation_id)
                self.assertEqual(desk.execute_calls, 1)
        self.assertEqual(self.desk.effects(), 4)

    def test_process_termination_after_atomic_commit_leaves_recoverable_running(self):
        operation = self.prepare()
        with self.assertRaises(SystemExit):
            self.dispatch(operation, desk=SQLiteDesk(self.desk_path, after_commit=crash))
        restarted = OperationJournal(self.journal_path, KEY)
        self.assertEqual(restarted.get(OWNER, operation.operation_id).state, 'running')
        self.assertEqual(restarted.recover(OWNER, operation.operation_id, self.desk).state, 'completed')
        self.assertEqual(self.desk.effects(), 1)

    def test_process_termination_before_commit_rolls_back_both_tables(self):
        operation = self.prepare()
        with self.assertRaises(SystemExit):
            self.dispatch(operation, desk=SQLiteDesk(self.desk_path, before_commit=crash))
        self.assertEqual(self.desk.effects(), 0)
        self.assertIsNone(self.desk.lookup(operation))
        self.assertEqual(self.recover(operation).state, 'uncertain')
        self.assertEqual(self.dispatch(operation).state, 'uncertain')
        self.assertEqual(self.desk.execute_calls, 0)

    def test_known_rejection_is_persisted_without_business_effect(self):
        payload = {'reject': True}
        operation = self.prepare(payload=payload)
        desk = SQLiteDesk(self.desk_path, after_commit=timeout)
        self.assertEqual(self.dispatch(operation, payload, desk).state, 'uncertain')
        result = self.recover(operation)
        self.assertEqual(result.state, 'rejected')
        self.assertEqual(result.result, {})
        self.assertEqual(self.dispatch(operation, payload), result)
        self.assertEqual(self.desk.effects(), 0)

    def test_owner_and_authenticated_session_isolation_before_any_desk_access(self):
        operation = self.prepare()
        desk = Mock()
        for owner in (Owner('another-user', OWNER.auth_session),
                      Owner(OWNER.subject, 'another-auth-session')):
            with self.subTest(owner=owner):
                for action in (
                    lambda: self.journal.get(owner, operation.operation_id),
                    lambda: self.journal.dispatch(owner, operation.operation_id, PAYLOAD, desk),
                    lambda: self.journal.recover(owner, operation.operation_id, desk),
                ):
                    with self.assertRaisesRegex(OperationNotFound, '^operation unavailable$'):
                        action()
        desk.assert_not_called()
        self.assertEqual(desk.mock_calls, [])

    def test_unknown_and_malformed_id_look_the_same(self):
        for operation_id in ('op_' + 'f' * 32, 'invalid', None):
            with self.assertRaisesRegex(OperationNotFound, '^operation unavailable$'):
                self.journal.get(OWNER, operation_id)

    def test_changed_payload_never_reaches_desk(self):
        operation = self.prepare()
        with self.assertRaises(OperationConflict):
            self.dispatch(operation, {'text': 'different item'})
        self.assertEqual(self.desk.execute_calls, 0)

    def test_receipt_mismatch_never_recovers_similar_or_other_users_work(self):
        operation = self.prepare()
        self.dispatch(operation, desk=SQLiteDesk(self.desk_path, after_commit=timeout))
        real = self.desk.lookup(operation)
        for changes in ({'operation_id': 'op_' + 'a' * 32}, {'owner_scope': 'other'},
                        {'kind': 'lost'}, {'request_hash': 'other'}):
            desk = Mock()
            desk.lookup.return_value = replace(real, **changes)
            self.assertEqual(self.recover(operation, desk).state, 'uncertain')
            desk.execute.assert_not_called()
        self.assertEqual(self.recover(operation).state, 'completed')

    def test_invalid_receipts_and_identifiers_remain_uncertain(self):
        operation = self.prepare()
        self.dispatch(operation, desk=Mock(execute=Mock(side_effect=timeout)))
        for receipt in (None, {}, replace(operation, state='completed', result={}),
                        replace(operation, state='completed', result={'item_id': True}),
                        replace(operation, state='completed', result={'item_id': ' '}),
                        replace(operation, state='completed', result={'item_id': 'x' * 121}),
                        replace(operation, state='completed', result={'item_id': 'I-1', 'private': 'secret'}),
                        replace(operation, state='rejected', result={'item_id': 'I-1'}),
                        replace(operation, state='prepared', result={} )):
            desk = Mock(lookup=Mock(return_value=receipt))
            self.assertEqual(self.recover(operation, desk).state, 'uncertain')
            desk.execute.assert_not_called()

    def test_running_and_unknown_lookup_do_not_retry_or_expire(self):
        operation = self.prepare()
        self.dispatch(operation, desk=Mock(execute=Mock(side_effect=timeout)))
        desk = Mock(lookup=Mock(return_value=replace(operation, state='running')))
        self.assertEqual(self.recover(operation, desk).state, 'running')
        desk.lookup.side_effect = TimeoutError('sensitive')
        self.assertEqual(self.dispatch(operation, desk=desk).state, 'uncertain')
        desk.execute.assert_not_called()

    def test_late_uncertainty_cannot_overwrite_completed_result(self):
        operation = self.prepare()
        self.dispatch(operation, desk=SQLiteDesk(self.desk_path, after_commit=timeout))
        entered, release = threading.Event(), threading.Event()
        def slow_lookup(original):
            entered.set()
            if not release.wait(10):
                raise AssertionError('test barrier timed out')
            raise TimeoutError()
        slow = Mock(lookup=Mock(side_effect=slow_lookup))
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(self.recover, operation, slow)
            self.assertTrue(entered.wait(10))
            result = self.recover(operation)
            release.set()
            self.assertEqual(future.result(10), result)
        self.assertEqual(self.journal.get(OWNER, operation.operation_id), result)

    def test_concurrent_preparation_and_dispatch_use_one_operation_and_effect(self):
        with ThreadPoolExecutor(8) as pool:
            prepared = list(pool.map(lambda _: self.prepare(), range(16)))
            self.assertEqual(len({o.operation_id for o in prepared}), 1)
            results = list(pool.map(self.dispatch, prepared))
        self.assertTrue(all(r.state in ('running', 'uncertain', 'completed') for r in results))
        self.assertEqual(self.recover(prepared[0]).state, 'completed')
        self.assertEqual(self.desk.effects(), 1)

    def test_separate_processes_and_restart_do_not_duplicate_effect(self):
        operation = self.prepare()
        args = (str(self.journal_path), str(self.desk_path), operation.operation_id)
        with multiprocessing.get_context('spawn').Pool(3) as pool:
            states = pool.map(process_replay, [args] * 6)
        self.assertIn('completed', states)
        self.assertEqual(self.recover(operation).state, 'completed')
        self.assertEqual(self.desk.effects(), 1)

    def test_real_process_exit_before_and_after_commit(self):
        for after_commit in (False, True):
            with self.subTest(after_commit=after_commit):
                operation = self.prepare(proof='hard-exit-' + str(after_commit))
                process = multiprocessing.get_context('spawn').Process(
                    target=process_exit, args=(str(self.journal_path), str(self.desk_path),
                                               operation.operation_id, after_commit))
                process.start()
                process.join(15)
                if process.is_alive():
                    process.terminate()
                    process.join(5)
                    self.fail('child process timed out')
                self.assertEqual(process.exitcode, 19)
                restarted = OperationJournal(self.journal_path, KEY)
                result = restarted.recover(OWNER, operation.operation_id, self.desk)
                self.assertEqual(result.state, 'completed' if after_commit else 'uncertain')
        self.assertEqual(self.desk.effects(), 1)

    def test_unavailable_journal_prevents_business_write(self):
        operation = self.prepare()
        self.journal.path = Path(self.tmp.name)  # DB를 열 수 없는 경우
        with self.assertRaises(sqlite3.OperationalError):
            self.dispatch(operation)
        self.assertEqual(self.desk.execute_calls, 0)

    def test_desk_itself_deduplicates_same_id_and_rejects_scope_or_hash_change(self):
        operation = self.prepare()
        with ThreadPoolExecutor(6) as pool:
            receipts = list(pool.map(lambda _: self.desk.execute(operation, PAYLOAD), range(12)))
        self.assertTrue(all(r == receipts[0] for r in receipts))
        self.assertEqual(self.desk.effects(), 1)
        with self.assertRaises(OperationNotFound):
            self.desk.lookup(replace(operation, owner_scope='wrong'))
        with self.assertRaises(OperationConflict):
            self.desk.execute(replace(operation, request_hash='wrong'), PAYLOAD)

    def test_journal_does_not_store_raw_owner_identity_draft_or_error(self):
        operation = self.prepare()
        self.dispatch(operation, desk=Mock(execute=Mock(side_effect=timeout)))
        with connection(self.journal_path) as db:
            dump = '\n'.join(db.iterdump())
        for private in ('fictional-user', 'server-auth-session', 'accepted-draft-1',
                        'fictional item', '가*명', 'sensitive error', KEY.decode()):
            self.assertNotIn(private, dump)
        self.assertIn(operation.operation_id, dump)

    def test_requires_explicit_key_and_server_owner_type(self):
        for key in (b'', b'short', 'not-bytes'):
            with self.assertRaises(ValueError):
                OperationJournal(self.journal_path, key)
        with self.assertRaises(ValueError):
            OperationJournal(':memory:', KEY)
        with self.assertRaises(ValueError):
            self.journal.prepare('browser-session-id', 'draft', 'found', PAYLOAD)
        with self.assertRaises(ValueError):
            Owner('', 'session')
        with self.assertRaises(ValueError):
            self.prepare(kind='unsupported')
        with self.assertRaises(ValueError):
            self.prepare(payload={'number': float('nan')})


if __name__ == '__main__':
    unittest.main()
