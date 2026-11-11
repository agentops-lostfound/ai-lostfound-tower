import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from agents.robot_api import check_robot_part, validate_robot_result
from agents.robot_part import load_robot_part
from robot.joint_motion import JOINTS
from robot.studio_pose_transport import StudioPoseTransport
from robot.tower_part import TowerRobot
from robot.studio_pose_worker import confirm_stop

FOLLOWER = 'bc50f050-d0a5-4430-af97-0486cdaec3a2'
VALUES = {name + '.pos': 0.0 for name in JOINTS}


class PartTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'poses.json'
        self.path.write_text(json.dumps({'pose_1': VALUES, 'pose_8': VALUES}), encoding='utf-8')
        self.motion = Mock()
        self.part = TowerRobot(motion=self.motion, poses_path=self.path, environ={})

    def test_constructor_and_loader_do_not_connect(self):
        with patch('subprocess.Popen') as start:
            part = TowerRobot(poses_path=self.path, environ={})
            self.assertEqual(check_robot_part(part)['missing'], [])
            self.assertEqual(check_robot_part(load_robot_part('robot.tower_part:TowerRobot'))['missing'], [])
            start.assert_not_called()
        self.assertFalse(part.robot_go_pose('pose_1', 'R1-1')['ok'])

    def test_valid_db_target_waits_for_motion_and_uses_duration(self):
        part = TowerRobot(motion=self.motion, poses_path=self.path,
                          environ={'TOWER_ROBOT_MOVE_SECONDS': '5'})
        self.assertTrue(part.robot_go_pose('pose_8', 'R4-2')['ok'])
        self.motion.move.assert_called_once_with('pose_8', 5, part.cancelled)

    def test_invalid_targets_do_not_move(self):
        for pose, slot in [('pose_9', 'R1-1'), ('home', 'R1-1'), ('pose_1', 'H-1'),
                           ('pose_1', 'S-1'), (None, 'R1-1'), ('pose_1', None), ('pose_8', 'R1-1')]:
            self.assertFalse(self.part.robot_go_pose(pose, slot)['ok'])
        self.motion.move.assert_not_called()

    def test_missing_or_bad_poses_and_invalid_duration_fail_closed(self):
        for path, env in [(self.path.with_name('missing.json'), {}),
                          (self.path, {'TOWER_ROBOT_MOVE_SECONDS': '2'})]:
            part = TowerRobot(motion=self.motion, poses_path=path, environ=env)
            self.assertFalse(part.robot_go_pose('pose_1', 'R1-1')['ok'])
        self.motion.move.assert_not_called()

    def test_pose_with_extra_axis_is_rejected_before_motion(self):
        values = {**VALUES, 'unexpected.pos': 0.0}
        self.path.write_text(json.dumps({'pose_1': values}), encoding='utf-8')
        part = TowerRobot(motion=self.motion, poses_path=self.path, environ={})
        self.assertFalse(part.robot_go_pose('pose_1', 'R1-1')['ok'])
        self.motion.move.assert_not_called()

    def test_failure_is_a_result_and_prevents_automatic_retry(self):
        self.motion.move.side_effect = RuntimeError('observations stale')
        result = self.part.robot_go_pose('pose_1', 'R1-1')
        self.assertEqual(validate_robot_result(result), [])
        self.assertFalse(result['ok'])
        self.assertFalse(self.part.robot_go_pose('pose_1', 'R1-1')['ok'])
        self.motion.move.assert_called_once()

    def test_stop_interrupts_wait_without_taking_motion_lock(self):
        entered, released = threading.Event(), threading.Event()
        self.motion.move.side_effect = lambda *args: (entered.set(), released.wait(2))
        self.motion.stop.side_effect = lambda: (released.set() or True)
        result = []
        thread = threading.Thread(target=lambda: result.append(self.part.robot_go_pose('pose_1', 'R1-1')))
        thread.start()
        self.assertTrue(entered.wait(1))
        self.assertFalse(self.part.robot_go_pose('pose_8', 'R4-2')['ok'])
        self.assertTrue(self.part.robot_stop()['ok'])
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertFalse(result[0]['ok'])
        self.assertFalse(self.part.robot_go_pose('pose_1', 'R1-1')['ok'])

    def test_unimplemented_operations_never_pretend_success(self):
        for method in ('robot_grasp', 'robot_verify_grasp', 'robot_deliver', 'robot_home'):
            result = getattr(self.part, method)()
            self.assertEqual(validate_robot_result(result), [])
            self.assertFalse(result['ok'])
        self.assertFalse(self.part.robot_approach([0, 0], [0, 0])['ok'])
        self.motion.move.assert_not_called()

    def test_stop_failure_does_not_raise_or_resume(self):
        self.motion.stop.side_effect = OSError('connection lost')
        self.assertFalse(self.part.robot_stop()['ok'])
        self.assertFalse(self.part.robot_go_pose('pose_1', 'R1-1')['ok'])


class FakePipe:
    def __init__(self, scenario='arrive'):
        self.time = 0.0
        self.scenario = scenario
        self.sent = []
        self.closed = False
        self.base = {'connected': True, 'follower_source': 'hold', 'is_recording': False,
                     'saved_pose_robot_id': FOLLOWER, 'saved_pose_names': ['pose_1'],
                     'saved_pose_status': 'idle'}
        self.events = [self.state(), self.observation()]

    def state(self, **data):
        return {'event': 'state', 'data': {**self.base, **data}}

    def observation(self):
        return {'event': 'observation', 'data': VALUES}

    def send(self, row):
        self.sent.append(row)
        if row['event'] == 'stop_saved_pose':
            self.events = [{'event': 'stop_result', 'request_id': row['data']['request_id'], 'ok': True}]
        if row['event'] == 'move_saved_pose':
            data = row['data']
            token = data['token'] if self.scenario != 'foreign' else 'another-client'
            self.events.append(self.state(saved_pose_status='moving', saved_pose_name='pose_1', saved_pose_token=token))
            if self.scenario == 'arrive':
                self.events.extend(self.observation() for _ in range(90))
                self.events.append(self.state(saved_pose_status='holding_target', saved_pose_name='pose_1', saved_pose_token=token))
                self.events.extend(self.observation() for _ in range(90))
                self.events.append(self.state(saved_pose_status='arrived', saved_pose_name='pose_1', saved_pose_token=None))
            elif self.scenario == 'error':
                self.events.append({'event': 'error', 'message': 'following error'})

    def receive(self):
        self.time += 0.05
        return self.events.pop(0) if self.events else None

    def close(self):
        self.closed = True


class TransportTests(unittest.TestCase):
    def transport(self, pipe):
        return StudioPoseTransport(FOLLOWER, socket_factory=lambda *args: pipe, clock=lambda: pipe.time)

    def test_recovery_snapshot_is_read_only_and_requires_correct_follower(self):
        pipe = FakePipe()
        result = self.transport(pipe).snapshot(threading.Event())
        self.assertEqual(result['positions'], VALUES)
        self.assertEqual(pipe.sent, [])
        self.assertTrue(pipe.closed)
        pipe = FakePipe()
        pipe.base['saved_pose_robot_id'] = 'another-follower'
        pipe.events = [pipe.state(), pipe.observation()]
        with self.assertRaises(ValueError):
            self.transport(pipe).snapshot(threading.Event())
        self.assertEqual(pipe.sent, [])

    def test_waits_past_profile_time_for_correlated_arrival(self):
        pipe = FakePipe()
        self.transport(pipe).move('pose_1', 3, threading.Event())
        self.assertGreater(pipe.time, 9)
        self.assertTrue(pipe.closed)
        self.assertTrue(any(r['event'] == 'saved_pose_heartbeat' for r in pipe.sent))
        command = pipe.sent[0]['data']
        self.assertEqual(command['duration_seconds'], 3)
        self.assertTrue(command['include_gripper'])
        self.assertNotIn('disconnect', [r['event'] for r in pipe.sent])

    def test_post_grasp_return_preserves_gripper_command(self):
        pipe = FakePipe()
        self.transport(pipe).move('pose_1', 3, threading.Event(), include_gripper=False)
        command = next(row['data'] for row in pipe.sent if row['event'] == 'move_saved_pose')
        self.assertIs(command['include_gripper'], False)
        self.assertTrue(pipe.closed)

    def test_invalid_gripper_option_does_not_open_connection(self):
        with patch('subprocess.Popen') as start, self.assertRaises(ValueError):
            StudioPoseTransport(FOLLOWER).move('pose_1', 3, threading.Event(), include_gripper='false')
        start.assert_not_called()

    def test_errors_stale_observations_and_foreign_control_stop(self):
        for scenario in ('error', 'stale', 'foreign'):
            with self.subTest(scenario=scenario):
                pipe = FakePipe(scenario)
                transport = self.transport(pipe)
                with self.assertRaises(ValueError):
                    transport.move('pose_1', 5, threading.Event())
                self.assertTrue(transport.stop_confirmed.is_set())
                self.assertIn('stop_saved_pose', [r['event'] for r in pipe.sent])

    def test_recording_teleop_or_missing_pose_rejects_before_command(self):
        for update in ({'is_recording': True}, {'follower_source': 'teleop'},
                       {'saved_pose_names': []}, {'saved_pose_status': 'moving'}):
            pipe = FakePipe()
            pipe.base.update(update)
            pipe.events = [pipe.state(), pipe.observation()]
            with self.assertRaises(ValueError):
                self.transport(pipe).move('pose_1', 3, threading.Event())
            self.assertEqual(pipe.sent, [])

    def test_cancelled_before_submission_never_moves(self):
        pipe = FakePipe()
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            self.transport(pipe).move('pose_1', 3, cancelled)
        self.assertEqual(pipe.sent, [])

    def test_stop_when_idle_requires_stopped_ack(self):
        pipe = FakePipe()
        self.assertTrue(self.transport(pipe).stop())
        self.assertEqual([r['event'] for r in pipe.sent], ['stop_saved_pose'])


    def test_cancel_during_attachment_returns_without_waiting_for_ready(self):
        pipe = FakePipe()
        pipe.events = []
        cancelled = threading.Event()
        receive = pipe.receive
        def cancel():
            cancelled.set()
            return receive()
        pipe.receive = cancel
        with self.assertRaises(InterruptedError):
            self.transport(pipe).move('pose_1', 3, cancelled)
        self.assertLess(pipe.time, 0.2)
        self.assertEqual(pipe.sent, [])
        self.assertTrue(pipe.closed)

    def test_uncertain_move_write_still_checks_stop(self):
        pipe = FakePipe()
        send = pipe.send
        def fail_after_write(row):
            send(row)
            if row['event'] == 'move_saved_pose':
                raise OSError('flush failed after write')
        pipe.send = fail_after_write
        transport = self.transport(pipe)
        with self.assertRaises(OSError):
            transport.move('pose_1', 3, threading.Event())
        self.assertTrue(transport.stop_confirmed.is_set())
        self.assertIn('stop_saved_pose', [r['event'] for r in pipe.sent])

    def test_stop_does_not_require_joint_observations(self):
        pipe = FakePipe()
        pipe.events = []
        self.assertTrue(self.transport(pipe).stop())
        self.assertLess(pipe.time, 0.5)

    def test_old_stopped_state_or_unrelated_response_cannot_confirm_stop(self):
        pipe = FakePipe()
        pipe.send = lambda row: pipe.sent.append(row)
        pipe.events = [pipe.state(saved_pose_status='stopped'),
                       {'event': 'stop_result', 'request_id': 'old', 'ok': True}]
        self.assertFalse(self.transport(pipe).stop())

    def test_failed_stop_confirmation_remains_visible(self):
        pipe = FakePipe('error')
        send = pipe.send
        def no_stop_reply(row):
            if row['event'] == 'stop_saved_pose':
                pipe.sent.append(row)
            else:
                send(row)
        pipe.send = no_stop_reply
        transport = self.transport(pipe)
        with self.assertRaisesRegex(RuntimeError, '정지 확인 실패'):
            transport.move('pose_1', 3, threading.Event())
        self.assertFalse(transport.stop_confirmed.is_set())

    def test_stop_during_move_does_not_compete_for_receive(self):
        pipe = FakePipe('stale')
        transport = self.transport(pipe)
        requested = threading.Event()
        stop_result = []
        receive = pipe.receive
        def stop_at_first_motion():
            if transport.socket is pipe and not requested.is_set():
                requested.set()
                thread = threading.Thread(target=lambda: stop_result.append(transport.stop()))
                thread.start()
                self.addCleanup(thread.join, 1)
                self.assertTrue(transport.stop_requested.wait(1))
            return receive()
        pipe.receive = stop_at_first_motion
        with self.assertRaises(InterruptedError):
            transport.move('pose_1', 3, threading.Event())
        self.assertTrue(transport.stop_confirmed.is_set())


class WorkerStopTests(unittest.TestCase):
    def test_stop_uses_fresh_metadata_when_identical_state_is_suppressed(self):
        client = Mock(error=None, shutdown_received=False)
        client.probe.return_value = {'status': 'running', 'instance_id': 'current',
            'state': {'data': {'connected': True, 'follower_source': 'hold',
                               'saved_pose_status': 'stopped'}}}
        adapter = Mock()
        self.assertTrue(confirm_stop(client, adapter, 'current'))
        client.apply.assert_called_once()
        client.probe.assert_called_once()

    def test_unaccepted_move_cannot_use_preexisting_stopped_snapshot(self):
        client = Mock(error=None, shutdown_received=False)
        client.probe.return_value = {'status': 'running', 'instance_id': 'current',
            'state': {'data': {'connected': True, 'follower_source': 'hold',
                               'saved_pose_status': 'stopped'}}}
        ticks = iter([0.0, 0.0, 2.0])
        self.assertFalse(confirm_stop(client, Mock(), 'current', expected_token='ours',
            clock=lambda: next(ticks), sleep=lambda _: None))

    def test_accepted_move_stop_can_use_metadata_without_duplicate_broadcast(self):
        client = Mock(error=None, shutdown_received=False)
        client.probe.return_value = {'status': 'running', 'instance_id': 'current',
            'state': {'data': {'connected': True, 'follower_source': 'hold',
                               'saved_pose_status': 'stopped'}}}
        self.assertTrue(confirm_stop(client, Mock(), 'current', expected_token='ours',
                                     was_accepted=lambda: True))

    def test_stop_rejects_other_runtime_generation(self):
        client = Mock(error=None, shutdown_received=False)
        client.probe.return_value = {'status': 'running', 'instance_id': 'other',
            'state': {'data': {'connected': True, 'follower_source': 'hold',
                               'saved_pose_status': 'stopped'}}}
        ticks = iter([0.0, 0.0, 2.0])
        self.assertFalse(confirm_stop(client, Mock(), 'current', clock=lambda: next(ticks), sleep=lambda _: None))

    def test_stop_never_treats_publish_as_confirmation(self):
        client = Mock(error=None, shutdown_received=False)
        client.probe.return_value = None
        ticks = iter([0.0, 0.0, 2.0])
        self.assertFalse(confirm_stop(client, Mock(), 'current', clock=lambda: next(ticks), sleep=lambda _: None))


if __name__ == '__main__':
    unittest.main()
