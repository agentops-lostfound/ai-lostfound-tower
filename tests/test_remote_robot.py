import http.client
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest
import urllib.error
import uuid
from unittest.mock import Mock, patch

from agents.robot_api import check_robot_part
from robot.remote_client import RemoteTowerRobot
from robot.remote_executor import Executor, make_server


class FakeRobot:
    def __init__(self, block=False, stop_ok=True):
        self.cancelled = threading.Event()
        self.entered, self.release = threading.Event(), threading.Event()
        self.block, self.stop_ok = block, stop_ok
        self.calls = []

    def robot_go_pose(self, pose_name, slot_id):
        self.calls.append((pose_name, slot_id))
        self.entered.set()
        if self.block:
            self.release.wait(3)
        return {'ok': not self.cancelled.is_set(), 'reason': 'cancelled' if self.cancelled.is_set() else ''}

    def robot_stop(self):
        self.cancelled.set()
        self.release.set()
        return {'ok': self.stop_ok, 'reason': ''}

    def robot_grasp(self):
        return {'ok': False, 'reason': 'Grasp not implemented'}


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.robot = FakeRobot()
        self.now = 100.
        self.factory = Mock(return_value=self.robot)
        self.engine = Executor(self.factory, clock=lambda: self.now)
        self.addCleanup(self.engine.close)

    def submit(self, job_id=None, **changes):
        body = dict(instance=self.engine.instance, job_id=job_id or str(uuid.uuid4()),
                    operation='go_pose', arguments={'pose_name': 'pose_1', 'slot_id': 'R1-1'}, approved=True)
        body.update(changes)
        return self.engine.submit(**body)

    def wait(self, job_id):
        self.engine.jobs[job_id]['thread'].join(2)
        self.assertFalse(self.engine.jobs[job_id]['thread'].is_alive())
        return self.engine.status(job_id)

    def test_startup_is_disarmed_and_never_constructs_robot(self):
        self.factory.assert_not_called()
        with self.assertRaises(ValueError):
            self.submit()
        self.assertEqual(self.robot.calls, [])

    def test_duplicate_id_executes_once_and_different_work_is_rejected(self):
        self.engine.arm()
        job_id = str(uuid.uuid4())
        self.submit(job_id)
        self.assertEqual(self.wait(job_id)['status'], 'completed')
        self.assertEqual(self.submit(job_id)['status'], 'completed')
        self.assertEqual(len(self.robot.calls), 1)
        with self.assertRaises(ValueError):
            self.submit(job_id, arguments={'pose_name': 'pose_2', 'slot_id': 'R1-2'})

    def test_invalid_slot_unapproved_and_arbitrary_commands_never_move(self):
        self.engine.arm()
        for changes in ({'arguments': {'pose_name': 'pose_2', 'slot_id': 'R1-1'}},
                        {'approved': False}, {'operation': 'manual_joint_control'},
                        {'operation': 'sequence', 'arguments': {'target': {'ok': False}}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.submit(**changes)
        self.assertEqual(self.robot.calls, [])

    def test_busy_job_blocks_another_and_lease_loss_cancels(self):
        self.robot.block = True
        self.engine.arm()
        row = self.submit()
        self.assertTrue(self.robot.entered.wait(1))
        with self.assertRaises(ValueError):
            self.submit()
        self.now += 6
        self.engine.expire()
        result = self.wait(row['job_id'])
        self.assertEqual(result['status'], 'cancelled')
        self.assertTrue(result['stop_confirmed'])
        self.assertFalse(self.engine.armed)

    def test_heartbeat_extends_control_lease_without_marking_arrival(self):
        self.robot.block = True
        self.engine.arm()
        row = self.submit()
        self.assertTrue(self.robot.entered.wait(1))
        self.now += 4
        self.engine.heartbeat(self.engine.instance, row['job_id'])
        self.now += 4
        self.engine.expire()
        self.assertEqual(self.engine.status(row['job_id'])['status'], 'running')
        self.assertEqual(len(self.robot.calls), 1)
        self.engine.stop(row['job_id'])
        self.wait(row['job_id'])

    def test_stop_before_registration_fences_late_submission_even_after_rearm(self):
        self.engine.arm()
        old_instance, job_id = self.engine.instance, str(uuid.uuid4())
        self.assertTrue(self.engine.stop(job_id)['ok'])
        self.engine.arm()
        self.assertNotEqual(self.engine.instance, old_instance)
        for instance in (old_instance, self.engine.instance):
            with self.assertRaises(ValueError):
                self.submit(job_id, instance=instance)
        self.assertEqual(self.robot.calls, [])

    def test_stop_failure_latches_and_duplicate_stop_cannot_claim_confirmation(self):
        self.robot.block, self.robot.stop_ok = True, False
        self.engine.arm()
        row = self.submit()
        self.assertTrue(self.robot.entered.wait(1))
        self.assertFalse(self.engine.stop(row['job_id'])['ok'])
        self.assertFalse(self.engine.stop()['ok'])
        self.wait(row['job_id'])
        self.assertFalse(self.engine.stop(row['job_id'])['ok'])
        with self.assertRaises(ValueError):
            self.engine.arm()

    def test_old_stop_does_not_stop_a_new_job(self):
        self.engine.arm()
        first = self.submit()
        self.wait(first['job_id'])
        self.robot.block = True
        self.robot.entered.clear()
        second = self.submit()
        self.assertTrue(self.robot.entered.wait(1))
        self.assertTrue(self.engine.stop(first['job_id'])['ok'])
        self.assertFalse(self.robot.cancelled.is_set())
        self.assertEqual(self.engine.active, second['job_id'])
        self.engine.stop(second['job_id'])
        self.wait(second['job_id'])


class RemoteHttpTests(unittest.TestCase):
    def setUp(self):
        self.robot = FakeRobot()
        self.engine = Executor(lambda: self.robot)
        self.token = secrets.token_urlsafe(32)
        self.server = make_server(self.engine, self.token, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = RemoteTowerRobot(url=self.url, token=self.token, expected_mode='simulation', sleep=lambda _: None)
        self.addCleanup(self.close)

    def close(self):
        self.engine.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def test_wrong_token_and_browser_origin_are_rejected(self):
        wrong = RemoteTowerRobot(url=self.url, token=secrets.token_urlsafe(32))
        with self.assertRaises(urllib.error.HTTPError) as exc:
            wrong.health()
        self.assertEqual(exc.exception.code, 403)
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('GET', '/v1/health', headers={'Authorization': 'Bearer ' + self.token,
                                                 'Origin': 'http://untrusted.example'})
        response = conn.getresponse()
        self.assertEqual(response.status, 403)
        response.read();conn.close()

    def test_remote_part_contract_and_no_connection_on_construction(self):
        self.assertEqual(check_robot_part(self.client)['missing'], [])
        self.assertFalse(self.engine.armed)
        self.assertEqual(self.robot.calls, [])
        from agents.backends import CompositeBackend
        fallback = Mock()
        backend = CompositeBackend(robot=self.client, fallback=fallback)
        with self.assertRaises(NotImplementedError):
            backend.robot_state()
        fallback.robot_state.assert_not_called()

    def test_allowed_tower_ip_still_cannot_arm_remotely(self):
        # Model a connection from the explicitly allowed tower. Arming still
        # belongs to the loopback operator, not to that authenticated peer.
        def tower_peer(request):
            original(request)
            request.client_address = ('10.10.21.21', 10000)
        # Use another server because its peer allowlist must include the tower.
        server = make_server(self.engine, self.token, port=0, allow_clients=['10.10.21.21'])
        original = server.RequestHandlerClass.setup
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server.RequestHandlerClass, 'setup', tower_peer):
                client = RemoteTowerRobot(url=f'http://127.0.0.1:{server.server_port}', token=self.token,
                                          expected_mode='simulation')
                with self.assertRaises(urllib.error.HTTPError) as exc:
                    client.arm_local()
                self.assertEqual(exc.exception.code, 403)
            self.assertFalse(self.engine.armed)
        finally:
            server.shutdown();server.server_close();thread.join(2)

    def test_arm_go_pose_and_real_mode_client_rejects_simulation(self):
        self.assertTrue(self.client.arm_local()['armed'])
        live_client = RemoteTowerRobot(url=self.url, token=self.token)
        self.assertFalse(live_client.robot_go_pose('pose_1', 'R1-1')['ok'])
        self.assertEqual(self.robot.calls, [])
        result = self.client.robot_go_pose('pose_1', 'R1-1')
        self.assertTrue(result['ok'])
        self.assertEqual(result['remote_mode'], 'simulation')
        self.assertEqual(self.robot.calls, [('pose_1', 'R1-1')])

    def test_unimplemented_grasp_is_not_reported_as_success(self):
        self.client.arm_local()
        result = self.client.robot_grasp()
        self.assertFalse(result['ok'])
        self.assertIn('not implemented', result['reason'])
        self.assertFalse(self.engine.armed)

    def test_ambiguous_submit_response_never_retries_and_tombstones_job(self):
        self.client.arm_local()
        real = self.client.request
        posts = []
        def lose_response(path, body=None):
            if path == '/v1/jobs':
                posts.append(body)
                raise TimeoutError('Submission outcome unknown')
            return real(path, body)
        self.client.request = lose_response
        result = self.client.robot_go_pose('pose_1', 'R1-1')
        self.assertFalse(result['ok'])
        self.assertTrue(result['stop_confirmed'])
        self.assertEqual(len(posts), 1)
        self.assertIn(posts[0]['job_id'], self.engine.cancelled_ids)
        self.client.robot_go_pose('pose_1', 'R1-1')
        self.assertEqual(len(posts), 1)
        self.assertEqual(self.robot.calls, [])

    def test_all_eight_full_sequences_over_http_use_taught_backend_and_preserve_db(self):
        from robot.tower_part import TowerRobot
        from robot.db_pose_sequence import SimulatedPoseMotion
        from tests.sequence_fixtures import taught_poses
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'poses.json'
            poses = taught_poses()
            path.write_text(json.dumps(poses), encoding='utf-8')
            self.engine.factory = lambda: TowerRobot(motion=SimulatedPoseMotion(poses), poses_path=path, environ={})
            self.client.arm_local()
            for n in range(1, 9):
                target = {'ok': True, 'item_id': 'TEST', 'number': n, 'pose_name': f'pose_{n}',
                          'slot_id': f'R{(n+1)//2}-{1 if n%2 else 2}'}
                result = self.client.run_pose_sequence_test(target)
                self.assertTrue(result['ok'], result)
                self.assertEqual(len(result['completed']), 11)
                self.assertTrue(result['test_only'])
                self.assertEqual(target['item_id'], 'TEST')

    def test_old_return_plan_is_rejected_before_any_job_or_motion(self):
        self.client.arm_local()
        self.engine.sequence_plans['R4-2'][5] = 'pose_8_return'
        target = {'ok': True, 'item_id': 'TEST', 'number': 8, 'pose_name': 'pose_8', 'slot_id': 'R4-2'}
        result = self.client.robot_run_sequence(target)
        self.assertFalse(result['ok'])
        self.assertIn('Sequence plan mismatch before motion', result['reason'])
        self.assertIn('stage 6', result['reason'])
        self.assertEqual(self.engine.jobs, {})
        self.assertEqual(self.robot.calls, [])
        self.assertTrue(self.engine.armed)

    def test_peer_without_plan_advertisement_is_rejected_before_submission(self):
        self.client.arm_local()
        real = self.client.request
        posts = []
        def older_peer(path, body=None):
            result = real(path, body)
            if path == '/v1/health':
                result.pop('sequence_plans', None)
            if path == '/v1/jobs':
                posts.append(body)
            return result
        self.client.request = older_peer
        target = {'ok': True, 'item_id': 'TEST', 'number': 8, 'pose_name': 'pose_8', 'slot_id': 'R4-2'}
        result = self.client.robot_run_sequence(target)
        self.assertFalse(result['ok'])
        self.assertIn('missing', result['reason'])
        self.assertEqual(posts, [])
        self.assertEqual(self.engine.jobs, {})

    def test_progress_failure_keeps_detail_job_and_rejected_stage_without_secret(self):
        from tests.sequence_fixtures import expected_sequence
        plan = expected_sequence(8)
        target = {'ok': True, 'item_id': 'TEST', 'number': 8, 'pose_name': 'pose_8', 'slot_id': 'R4-2'}
        event = {'event': 'stage_started', 'index': 6, 'total': 11,
                 'pose_name': 'pose_8', 'command_pose': 'pose_8'}
        def replies(path, body=None):
            if path == '/v1/health':
                return {'mode': 'simulation', 'armed': True, 'instance': 'test',
                        'sequence_plans': {'R4-2': plan}}
            if path == '/v1/jobs':
                return {'job_id': body['job_id'], 'events': [event], 'status': 'running'}
            self.fail(path)
        self.client.request = replies
        self.client.robot_stop = Mock(return_value={'ok': True})
        def reject(_):
            raise ValueError('expected pose_8_return; credential=' + self.token)
        result = self.client.robot_run_sequence(target, progress=reject)
        self.assertFalse(result['ok'])
        self.assertIn('expected pose_8_return', result['reason'])
        self.assertNotIn(self.token, json.dumps(result))
        self.assertEqual(result['failed_progress'], event)
        uuid.UUID(result['job_id'])
        self.client.robot_stop.assert_called_once()
        self.assertTrue(self.client.faulted)

    def test_only_new_local_arming_epoch_allows_an_explicit_call_after_uncertain_delivery(self):
        self.client.arm_local()
        real = self.client.request
        def lose_once(path, body=None):
            if path == '/v1/jobs':
                raise TimeoutError('Unknown submission')
            return real(path, body)
        self.client.request = lose_once
        self.assertFalse(self.client.robot_go_pose('pose_1', 'R1-1')['ok'])
        self.client.request = real
        self.assertFalse(self.client.robot_go_pose('pose_1', 'R1-1')['ok'])
        operator = RemoteTowerRobot(url=self.url, token=self.token, expected_mode='simulation')
        operator.arm_local()
        self.assertTrue(self.client.robot_go_pose('pose_1', 'R1-1')['ok'])
        self.assertEqual(self.robot.calls, [('pose_1', 'R1-1')])

    def test_keyboard_interrupt_requests_stop_instead_of_leaving_a_job_running(self):
        self.client.arm_local()
        real = self.client.request
        def interrupted(path, body=None):
            if path == '/v1/jobs':
                raise KeyboardInterrupt()
            return real(path, body)
        self.client.request = interrupted
        result = self.client.robot_go_pose('pose_1', 'R1-1')
        self.assertFalse(result['ok'])
        self.assertTrue(result['stop_confirmed'])
        self.assertFalse(self.engine.armed)

    def test_stop_during_preparation_is_not_cleared_before_submission(self):
        self.client.arm_local()
        original = self.client.request
        intercept = True
        posts = []

        def stop_before_health_returns(path, body=None, **kwargs):
            nonlocal intercept
            result = original(path, body, **kwargs)
            if path == '/v1/jobs':
                posts.append(body)
            if path == '/v1/health' and intercept:
                intercept = False
                self.client.robot_stop()
            return result
        self.client.request = stop_before_health_returns
        result = self.client.robot_go_pose('pose_1', 'R1-1')
        self.assertFalse(result['ok'])
        self.assertEqual(posts, [])
        self.assertEqual(self.robot.calls, [])


if __name__ == '__main__':
    unittest.main()
