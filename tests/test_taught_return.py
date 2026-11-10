"""Showcase's real kiosk API -> authenticated RPC -> simulated taught motors.

No Studio, hardware, external network, secrets files or PostgreSQL are used.
"""
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from datetime import date
from unittest.mock import Mock, patch

from agents.contracts import DECISION_RETURNED, DECISION_STOPPED, HANDOVER_WAIT
from agents.sim_director import build_sim_service
from agents.taught_return import enabled
from robot.db_pose_sequence import SimulatedPoseMotion
from robot.remote_client import RemoteTowerRobot
from robot.remote_executor import Executor, make_server
from robot.tower_part import TowerRobot
from tests.sequence_fixtures import taught_poses, expected_sequence


class ControlledMotion(SimulatedPoseMotion):
    def __init__(self, poses):
        super().__init__(poses)
        self.count = 0
        self.fail_at = None
        self.block_at = None
        self.entered = threading.Event()
        self.release = threading.Event()

    def move(self, pose, duration, cancelled, **kwargs):
        self.count += 1
        if self.count == self.block_at:
            self.entered.set()
            while not self.release.wait(.01):
                if cancelled.is_set():
                    raise InterruptedError('Stopped while waiting for arrival')
        if self.count == self.fail_at:
            raise ValueError('Arrival unavailable')
        return super().move(pose, duration, cancelled, **kwargs)


class TaughtReturnTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.poses = taught_poses()
        self.path = Path(self.folder.name) / 'poses.json'
        self.path.write_text(json.dumps(self.poses), encoding='utf-8')
        self.motion = ControlledMotion(self.poses)
        self.engine = Executor(lambda: TowerRobot(motion=self.motion, poses_path=self.path, environ={}))
        self.token = secrets.token_urlsafe(32)
        self.server = make_server(self.engine, self.token, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.client = RemoteTowerRobot(url=self.url, token=self.token, expected_mode='simulation')
        self.env = {'TOWER_SIM': '1', 'TOWER_SIM_SPEED': '0', 'TOWER_AGENT_TALK': '0',
                    'TOWER_GPU_LEASE': '0', 'LF_LANGFUSE': '0', 'TOWER_ROBOT_SEQUENCE': 'taught',
                    'TOWER_ROBOT_TARGET': 'db', 'TOWER_ROBOT_PART': 'robot.remote_client:RemoteTowerRobot',
                    'TOWER_REMOTE_ROBOT_URL': self.url, 'TOWER_REMOTE_ROBOT_TOKEN': self.token,
                    'TOWER_REMOTE_ROBOT_MODE': 'simulation'}
        self.env_patch = patch.dict(os.environ, self.env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.svc = build_sim_service(self.env)
        self.item_id = next(iter(self.svc.world.items))
        self.claim = self.svc.create_claim({
            'item_id': self.item_id, 'consent': True, 'name_masked': '시*인', 'id_no_masked': '9*****',
            'id_verified': True, 'description': {'category': '핸드크림', 'color': '분홍'},
            'quiz': [{'field': 'color', 'passed': True}], 'visit_date': date.today().isoformat()})
        self.body = {'machine_id': 'CENTER', 'claim_id': self.claim['claim_id'], 'id_no_masked': '9*****'}

    def close(self):
        self.motion.release.set()
        self.engine.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def api(self):
        from fastapi.testclient import TestClient
        from agents.api import build_app
        from agents.admin_auth import AdminAuth
        return TestClient(build_app(self.svc, chatbot=Mock(), admin_auth=AdminAuth('', secret='test')))

    def test_kiosk_button_waits_for_all_11_arrivals_and_requires_staff_handover(self):
        self.client.arm_local()
        # Use the director/story binding that the showcase's lost/pickup tabs use.
        with patch.object(self.svc, 'create_claim', return_value=self.claim), \
                patch.object(self.svc.sim, '_spawn', side_effect=lambda fn, *args: fn(*args)):
            story = self.svc.sim._claim({'category': '핸드크림', 'color': '분홍'}, None,
                                        [{'item_id': self.item_id}], set(), {'visit': 'kiosk'})
        api = self.api()
        result = api.post('/api/kiosk/returns', json=self.body)
        self.assertEqual(result.status_code, 200, result.text)
        row = result.json()
        self.assertEqual(row['decision'], DECISION_RETURNED, row)
        self.assertEqual(row['robot_sequence']['completed'], expected_sequence(5))
        self.assertTrue(row['robot_sequence']['verification_required'])
        self.assertEqual(self.motion.count, 11)
        self.assertEqual(self.svc.world.db_get_item(self.item_id)['status'], HANDOVER_WAIT)
        self.assertFalse(self.svc.sim.auto_handover)
        self.assertEqual(self.svc.world.items[self.item_id]['loc'], 'basket')
        self.assertEqual(api.post('/api/kiosk/returns', json=self.body).status_code, 409)
        self.assertEqual(self.motion.count, 11)
        saved = self.svc.get_case(row['case_id'])
        self.assertTrue(any('11/11' in step['step'] and '도착' in step['step'] for step in saved['steps']))
        state = api.get('/api/admin/live/state?detail=1').json()
        self.assertEqual(state['robot_control']['mode'], 'taught_remote')
        self.assertFalse(state['world']['arm']['joints'])
        stages = {s['key']: s for s in self.svc.board.stories[story['story_id']]['stages']}
        self.assertEqual(stages['deliver']['state'], 'done')
        self.assertEqual(stages['handover']['state'], 'todo')
        self.assertIn('11/11', stages['deliver']['detail'])
        self.assertEqual(api.post('/sim/reset', json={}).status_code, 409)

    def test_no_fake_success_when_executor_is_not_armed(self):
        result = self.svc.kiosk_return(self.body)
        self.assertEqual(result['decision'], DECISION_STOPPED)
        self.assertEqual(self.motion.count, 0)
        self.assertNotEqual(self.svc.world.db_get_item(self.item_id)['status'], HANDOVER_WAIT)

    def test_wrong_identity_and_client_supplied_slot_never_move(self):
        self.client.arm_local()
        api = self.api()
        for body in ({**self.body, 'id_no_masked': 'wrong'}, {**self.body, 'slot_id': 'R1-1'}):
            self.assertEqual(api.post('/api/kiosk/returns', json=body).status_code, 422)
        self.assertEqual(self.motion.count, 0)

    def test_failed_move_records_last_arrival_and_never_retries(self):
        self.client.arm_local()
        self.motion.fail_at = 7
        row = self.svc.kiosk_return(self.body)
        self.assertEqual(row['decision'], DECISION_STOPPED, row)
        self.assertEqual(row['robot_sequence']['completed'], expected_sequence(5)[:6])
        self.assertEqual(row['robot_sequence']['failed_pose'], 'outlet_return_1')
        self.assertEqual(self.motion.count, 7)
        self.assertFalse(self.engine.armed)
        self.assertNotEqual(self.svc.world.db_get_item(self.item_id)['status'], HANDOVER_WAIT)

    def test_blocked_arrival_keeps_return_pending_and_stop_prevents_remaining_stages(self):
        self.client.arm_local()
        self.motion.block_at = 5
        rows = []
        worker = threading.Thread(target=lambda: rows.append(self.svc.kiosk_return(self.body)))
        worker.start()
        try:
            self.assertTrue(self.motion.entered.wait(3))
            self.assertEqual(self.svc.world.db_get_item(self.item_id)['status'], '반환 중')
            self.assertTrue(self.svc.health()['busy'])
            from agents.service import Conflict
            with self.assertRaises(Conflict):
                self.svc.kiosk_return(self.body)
            self.assertTrue(self.svc.stop_robot()['ok'])
        finally:
            self.motion.release.set()
            worker.join(4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(rows[0]['decision'], DECISION_STOPPED)
        self.assertEqual(self.motion.count, 5)
        self.assertLess(len(rows[0]['robot_sequence']['completed']), 5)

    def test_all_eight_routes_stream_ordered_arrivals_over_rpc(self):
        self.client.arm_local()
        for n in range(1, 9):
            target = {'ok': True, 'item_id': 'TEST', 'number': n, 'pose_name': f'pose_{n}',
                      'slot_id': f'R{(n+1)//2}-{1 if n%2 else 2}'}
            events = []
            result = self.client.robot_run_sequence(target, progress=events.append)
            self.assertTrue(result['ok'], result)
            self.assertFalse(result['test_only'])
            self.assertTrue(result['motion_complete'])
            self.assertEqual(len(events), 22)
            self.assertEqual([e['pose_name'] for e in events if e['event'] == 'stage_arrived'], expected_sequence(n))

    def test_live_operation_requires_locally_enabled_slot(self):
        self.engine.live = True
        self.engine.arm()
        target = self.svc.robot_target(self.item_id)
        import uuid
        with self.assertRaises(ValueError):
            self.engine.submit(self.engine.instance, str(uuid.uuid4()), 'taught_sequence', {'target': target}, True)
        self.assertEqual(self.motion.count, 0)

    def test_enabled_config_requires_explicit_remote_db_mode(self):
        for key, value in (('TOWER_ROBOT_TARGET', 'vision'), ('TOWER_ROBOT_PART', ''),
                           ('TOWER_ROBOT_SEQUENCE', 'typo')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                enabled({**self.env, key: value})
        self.assertFalse(enabled({}))

    def test_missing_arrival_events_cannot_be_replaced_by_an_ok_result(self):
        self.client.arm_local()
        part = self.svc.backend_factory()._route['robot_stop']
        claimed = {'ok': True, 'test_only': False, 'motion_complete': True,
                   'item_id': self.item_id, 'completed': expected_sequence(5)}
        with patch.object(part, 'robot_run_sequence', return_value=claimed):
            result = self.svc.kiosk_return(self.body)
        self.assertEqual(result['decision'], DECISION_STOPPED)
        self.assertNotEqual(self.svc.world.db_get_item(self.item_id)['status'], HANDOVER_WAIT)
        self.assertEqual(self.motion.count, 0)

    def test_lost_message_waits_for_kiosk_instead_of_automatically_moving_real_robot(self):
        self.client.arm_local()
        # Avoid making a second claim for the existing item; inspect the
        # director's actual claim path with a controlled claim store response.
        with patch.object(self.svc, 'create_claim', return_value=self.claim), patch.object(self.svc.sim, '_spawn') as spawn:
            row = self.svc.sim._claim({'category': '핸드크림', 'color': '분홍'}, None,
                                      [{'item_id': self.item_id}], set(), {})
        self.assertEqual(row['visit'], 'kiosk')
        self.assertIs(spawn.call_args.args[-1], True)
        self.assertEqual(self.motion.count, 0)


if __name__ == '__main__':
    unittest.main()
