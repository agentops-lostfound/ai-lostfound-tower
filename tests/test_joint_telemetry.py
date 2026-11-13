from datetime import datetime, timedelta, timezone
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import Mock

from robot.joint_motion import JOINTS
from robot.joint_telemetry import JointTelemetry, load_coordinates, received_observation
from robot.remote_executor import Executor, make_server
from robot.studio_joint_worker import ObservationBuffer
from robot.vendor_coordinates import VendorCoordinates


def positions():
    return {name + '.pos': (25. if name == 'gripper' else 20.) for name in JOINTS}


def calibration():
    return {name: {'drive_mode': 0, 'range_min': 500, 'range_max': 3500} for name in JOINTS}


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.wall = datetime(2026, 11, 11, tzinfo=timezone.utc)
        self.coordinates = VendorCoordinates(calibration())
        self.telemetry = JointTelemetry(coordinates=self.coordinates,
                                        clock=lambda: self.now, utcnow=lambda: self.wall)

    def row(self, **changes):
        return dict(available=True, positions=positions(), read_at=self.wall.isoformat(), **changes)

    def test_before_first_observation_is_unavailable(self):
        self.assertFalse(self.telemetry.snapshot('instance')['available'])

    def test_degrees_use_existing_vendor_conversion_and_gripper_percent(self):
        self.telemetry.accept(self.row())
        response = self.telemetry.snapshot('instance')
        self.assertTrue(response['available'])
        self.assertEqual(response['unit'], 'normalized')
        self.assertEqual(response['degrees'], self.coordinates.degrees(positions()))
        self.assertEqual(response['degrees']['gripper.pos'], 25.)
        self.assertEqual(response['source'], 'studio_observation')
        self.assertEqual(response['instance'], 'instance')

    def test_no_calibration_preserves_normalized_and_null_degrees(self):
        self.telemetry.coordinates = None
        self.telemetry.accept(self.row())
        self.assertIsNone(self.telemetry.snapshot('i')['degrees'])

    def test_stale_values_do_not_become_fresh_on_each_request(self):
        self.telemetry.accept(self.row())
        first = self.telemetry.snapshot('i')
        self.now += .5
        self.assertEqual(self.telemetry.snapshot('i')['read_at'], first['read_at'])
        self.now += .6
        self.assertFalse(self.telemetry.snapshot('i')['available'])

    def test_pipe_backlog_timestamp_is_rejected(self):
        row = self.row()
        row['read_at'] = (self.wall - timedelta(seconds=2)).isoformat()
        self.telemetry.accept(row)
        self.assertFalse(self.telemetry.snapshot('i')['available'])

    def test_original_sample_age_is_counted(self):
        row = self.row()
        row['read_at'] = (self.wall - timedelta(seconds=.8)).isoformat()
        self.telemetry.accept(row)
        self.assertTrue(self.telemetry.snapshot('i')['available'])
        self.now += .3
        self.assertFalse(self.telemetry.snapshot('i')['available'])

    def test_wsl_clock_skew_does_not_make_current_sample_unavailable(self):
        row = self.row()
        row['read_at'] = (self.wall + timedelta(seconds=30)).isoformat()
        row['sample_age_seconds'] = .02
        received = received_observation(row, .1, self.wall)
        self.telemetry.accept(received)
        result = self.telemetry.snapshot('i')
        self.assertTrue(result['available'])
        self.assertEqual(result['read_at'], (self.wall - timedelta(seconds=.12)).isoformat())

    def test_slow_or_backlogged_observer_response_is_unavailable(self):
        row = {**self.row(), 'sample_age_seconds': .01}
        self.telemetry.accept(received_observation(row, 2., self.wall))
        self.assertFalse(self.telemetry.snapshot('i')['available'])

    def test_invalid_observer_age_is_rejected(self):
        for age in (-1, float('nan'), None, True):
            with self.subTest(age=age), self.assertRaises(ValueError):
                received_observation({**self.row(), 'sample_age_seconds': age}, .1, self.wall)

    def test_invalid_sample_and_disconnect_clear_previous_values(self):
        for bad in (None, {}, {'shoulder_pan.pos': 3}, {**positions(), 'gripper.pos': float('nan')},
                    {**positions(), 'elbow_flex.pos': True}):
            with self.subTest(bad=bad):
                self.telemetry.accept(self.row())
                row = self.row()
                row['positions'] = bad
                self.telemetry.accept(row)
                self.assertFalse(self.telemetry.snapshot('i')['available'])
        self.telemetry.accept(self.row())
        self.telemetry.accept({'available': False})
        self.assertFalse(self.telemetry.snapshot('i')['available'])

    def test_measured_values_are_not_clamped_to_calibrated_range(self):
        row = self.row()
        row['positions']['wrist_flex.pos'] = 101.
        self.telemetry.accept(row)
        result = self.telemetry.snapshot('i')
        self.assertEqual(result['positions']['wrist_flex.pos'], 101.)
        self.assertIsNone(result['degrees'])

    def test_snapshot_cannot_mutate_cache(self):
        self.telemetry.accept(self.row())
        result = self.telemetry.snapshot('i')
        result['positions']['gripper.pos'] = 99
        result['degrees']['gripper.pos'] = 99
        self.assertEqual(self.telemetry.snapshot('i')['positions']['gripper.pos'], 25)
        self.assertEqual(self.telemetry.snapshot('i')['degrees']['gripper.pos'], 25)

    def test_calibration_is_bound_to_follower_and_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'calibration.json'
            path.write_text(json.dumps({'follower_id': 'one', 'calibration': calibration()}))
            self.assertIsInstance(load_coordinates(path, 'one'), VendorCoordinates)
            with self.assertRaises(ValueError):
                load_coordinates(path, 'two')
            path.write_text('[]')
            with self.assertRaises(ValueError):
                load_coordinates(path, 'one')
            data = calibration()
            data['elbow_flex']['drive_mode'] = 1
            path.write_text(json.dumps({'follower_id': 'one', 'calibration': data}))
            with self.assertRaises(ValueError):
                load_coordinates(path, 'one')


class ObservationBufferTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.buffer = ObservationBuffer(clock=lambda: self.now)
        self.metadata = {'instance_id': 'generation-1', 'status': 'running',
                         'state': {'data': {'connected': True, 'follower_source': 'saved_pose'}}}
        self.buffer.attach(self.metadata)

    def tick(self, instance='generation-1'):
        self.buffer.receive({'event': 'observation', 'data': positions(),
                             'actions': {'gripper.pos': 99}, 'leader': {'gripper.pos': 88}}, instance)

    def test_reads_follower_while_moving_without_actions_or_leader(self):
        self.tick()
        self.assertEqual(self.buffer.snapshot()['positions'], positions())
        self.assertNotIn('actions', self.buffer.snapshot())
        self.assertNotIn('leader', self.buffer.snapshot())

    def test_old_generation_disconnected_and_stale_ticks_unavailable(self):
        self.tick('old-generation')
        self.assertFalse(self.buffer.snapshot()['available'])
        self.tick()
        self.now += .6
        self.assertFalse(self.buffer.snapshot()['available'])
        self.tick()
        self.buffer.attach(None)
        self.assertFalse(self.buffer.snapshot()['available'])

    def test_runtime_generation_change_clears_old_sample_until_new_tick(self):
        self.tick()
        self.buffer.attach({**self.metadata, 'instance_id': 'generation-2'})
        self.assertFalse(self.buffer.snapshot()['available'])
        self.tick()
        self.assertFalse(self.buffer.snapshot()['available'])
        self.tick('generation-2')
        self.assertTrue(self.buffer.snapshot()['available'])

    def test_nonfatal_command_rejection_does_not_stop_observer(self):
        self.tick()
        self.buffer.receive({'event': 'error', 'message': 'command rejected'}, 'generation-1')
        self.assertTrue(self.buffer.snapshot()['available'])
        self.buffer.receive({'event': 'error'}, 'generation-1', fatal=True)
        self.assertFalse(self.buffer.snapshot()['available'])

    def test_shutdown_and_disconnected_state_invalidate_sample(self):
        for event in ({'event': 'lifecycle', 'data': {'event': 'shutdown'}},
                      {'event': 'state', 'data': {'connected': False}}):
            self.buffer.attach(self.metadata)
            self.tick()
            self.buffer.receive(event, 'generation-1')
            self.assertFalse(self.buffer.snapshot()['available'])


class JointEndpointTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.telemetry = JointTelemetry(clock=lambda: self.now)
        self.robot = Mock(error='')
        self.factory, self.readiness = Mock(return_value=self.robot), Mock()
        self.engine = Executor(self.factory, live=True, readiness=self.readiness,
                               clock=lambda: self.now, joint_telemetry=self.telemetry)
        self.token = 'a-test-token-with-at-least-32-characters'
        self.server = make_server(self.engine, self.token, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.robot.release.set() if hasattr(self.robot, 'release') else None
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.engine.close()

    def get(self, **headers):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=1)
        conn.request('GET', '/v1/joints', headers={'Authorization': 'Bearer ' + self.token, **headers})
        response = conn.getresponse()
        status, data = response.status, json.loads(response.read())
        conn.close()
        return status, data

    def test_same_authentication_and_browser_origin_rejection(self):
        self.assertEqual(self.get(Authorization='Bearer wrong')[0], 403)
        self.assertEqual(self.get(Origin='http://example.test')[0], 403)
        self.assertEqual(self.get()[0], 200)

    def test_disarmed_queries_and_missing_observation_never_construct_robot(self):
        for _ in range(5):
            status, result = self.get()
            self.assertEqual(status, 200)
            self.assertFalse(result['available'])
        self.factory.assert_not_called()
        self.readiness.assert_not_called()
        self.assertFalse(self.engine.armed)
        self.assertIsNone(self.engine.active)
        self.assertEqual(self.robot.mock_calls, [])

    def test_queries_do_not_wait_for_control_lock(self):
        with self.engine.lock:
            self.assertEqual(self.get()[0], 200)

    def test_queries_and_observer_failure_do_not_touch_running_job_or_lease(self):
        entered, release = threading.Event(), threading.Event()
        self.robot.release = release
        def move(**kwargs):
            entered.set()
            release.wait(5)
            return {'ok': True}
        self.robot.robot_go_pose.side_effect = move
        self.engine.arm()
        job = self.engine.submit(self.engine.instance, str(uuid.uuid4()), 'go_pose',
                                 {'slot_id': 'R1-1', 'pose_name': 'pose_1'}, True)
        self.assertTrue(entered.wait(1))
        heartbeat = self.engine.jobs[job['job_id']]['heartbeat']
        self.telemetry.accept({'available': True, 'positions': positions(),
                               'read_at': datetime.now(timezone.utc).isoformat()})
        for _ in range(5):
            self.assertTrue(self.get()[1]['available'])
        self.telemetry.unavailable()
        self.assertFalse(self.get()[1]['available'])
        self.assertTrue(self.engine.armed)
        self.assertEqual(self.engine.status(job['job_id'])['status'], 'running')
        self.assertEqual(self.engine.jobs[job['job_id']]['heartbeat'], heartbeat)
        self.robot.robot_stop.assert_not_called()
        self.factory.assert_called_once()
        self.readiness.assert_called_once()
        release.set()
        self.engine.jobs[job['job_id']]['thread'].join(1)
        self.assertEqual(self.engine.status(job['job_id'])['status'], 'completed')
