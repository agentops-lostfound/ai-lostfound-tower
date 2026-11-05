import csv
import tempfile
import unittest
from pathlib import Path
from robot.panel_core import Panel,KEYS,SPEEDS,import_recorded_poses
from robot.panel_transport import Simulation


class RobotPanelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.panel=Panel(self.temp.name);self.backend=Simulation()
        self.panel.observe(self.backend.snapshot())

    def test_stop_requires_repair_and_two_confirmations(self):
        with self.assertRaises(ValueError):self.panel.confirm()
        self.panel.repair();self.panel.edit(0,2);self.panel.confirm()
        self.assertFalse(self.panel.moving)
        self.panel.confirm();self.assertTrue(self.panel.moving)
        self.panel.stop();self.assertIsNone(self.panel.next_step())
        self.panel.repair();self.assertFalse(self.panel.moving)
        self.assertEqual(self.panel.target,self.panel.current)

    def test_each_speed_is_bounded_and_reaches_target(self):
        for speed in SPEEDS:
            self.panel.stop();self.panel.repair();self.panel.speed=speed
            self.panel.edit(0,1);self.panel.confirm();self.panel.confirm()
            for _ in range(100):
                point=self.panel.next_step()
                if point is None:break
                baseline=self.panel.commanded.copy()
                self.assertLessEqual(max(abs(point[k]-baseline[k]) for k in KEYS),SPEEDS[speed]+1e-9)
                self.backend.step(point,self.panel.current);self.panel.commanded=point
                self.panel.observe(self.backend.snapshot())
            self.assertFalse(self.panel.moving)
            self.assertAlmostEqual(self.panel.current[KEYS[0]],1)
            self.backend.values={k:0.0 for k in KEYS};self.panel.observe(self.backend.snapshot())

    def test_gripper_edit_and_out_of_range_rejected(self):
        for index,value in [(5,10),(0,101),(0,float('nan'))]:
            with self.assertRaises(ValueError):self.panel.edit(index,value)

    def test_pose_persistence_and_preview_no_movement(self):
        self.panel.save('home');self.panel.edit(0,20);self.panel.load('home')
        self.assertFalse(self.panel.moving)
        restored=Panel(self.temp.name);self.assertIn('home',restored.poses)

    def test_csv_header_unit_and_append(self):
        path=self.panel.export_csv();self.panel.export_csv()
        with path.open(encoding='utf-8') as stream:rows=list(csv.reader(stream))
        self.assertEqual(len(rows),3);self.assertEqual(rows[1][1],'studio_normalized')
        self.assertEqual(rows[0][-6:],KEYS)

    def test_pose_name_cannot_escape_directory(self):
        with self.assertRaises(ValueError):self.panel.save('../escape')

    def test_import_does_not_overwrite_operator_custom_pose(self):
        import json
        self.panel.save('home')
        root=Path(self.temp.name)/'recorded'/'20261105_home';root.mkdir(parents=True)
        other={k:20.0 for k in KEYS}
        (root/'pose.json').write_text(json.dumps({'unit':'studio_normalized','samples':[{'joints':other}]}))
        import_recorded_poses(self.panel,root.parent)
        self.assertEqual(self.panel.poses['home'][KEYS[0]],0)

    def test_editing_during_motion_rejected(self):
        self.panel.repair();self.panel.edit(0,10);self.panel.confirm();self.panel.confirm()
        with self.assertRaises(ValueError):self.panel.load('home')
        with self.assertRaises(ValueError):self.panel.edit(0,11)

    def test_render_simulation_without_window(self):
        from robot.control_panel import render
        frame=render(self.panel,self.backend)
        self.assertEqual(frame.shape,(650,1040,3))

    def test_duplicate_panel_lock_released_on_close(self):
        from robot.panel_lock import PanelLock
        path=Path(self.temp.name)/'panel.lock'
        first=PanelLock(path)
        try:
            with self.assertRaises(RuntimeError):PanelLock(path)
        finally:first.close()
        second=PanelLock(path);second.close()

    def test_connection_rejection_reason_is_preserved(self):
        import threading
        from types import SimpleNamespace
        from robot.panel_transport import Studio
        backend=Studio.__new__(Studio)
        backend.lock=threading.Lock();backend.closed=False;backend.capable=False
        backend.error=None;backend.pending=None
        backend.ws=SimpleNamespace(recv=lambda:'{"event":"error","message":"Another manual panel already attached"}')
        backend._receive()
        self.assertEqual(backend.error,'Another manual panel already attached')

    def test_gripper_feedback_does_not_block_arm_step(self):
        from robot.panel_transport import step_feedback
        target={k:0.0 for k in KEYS};actions=dict(target);measured=dict(target)
        measured['gripper.pos']=0.4;actions['gripper.pos']=0.3
        ack,reached,errors=step_feedback(target,actions,measured)
        self.assertTrue(ack);self.assertTrue(reached)
        self.assertNotIn('gripper.pos',errors)

    def test_arm_tracking_or_missing_ack_still_blocks(self):
        from robot.panel_transport import step_feedback
        target={k:0.0 for k in KEYS};measured=dict(target)
        measured['shoulder_lift.pos']=0.4
        ack,reached,_=step_feedback(target,target,measured)
        self.assertTrue(ack);self.assertFalse(reached)
        self.assertFalse(step_feedback(target,None,target)[0])

    def test_small_lag_does_not_require_arrival_each_step(self):
        self.panel.repair();self.panel.speed=2;self.panel.edit(0,1)
        self.panel.confirm();self.panel.confirm()
        for _ in range(3):
            point=self.panel.next_step()
            self.assertIsNotNone(point)
            self.panel.commanded=point
        self.assertAlmostEqual(point[KEYS[0]],0.3)
        # A servo that moves only after >0.2 can now follow, without relaxing final arrival.
        self.panel.observe(point)
        self.assertIsNotNone(self.panel.next_step())

    def test_stalled_arm_cannot_accumulate_targets(self):
        from unittest.mock import patch
        self.panel.repair();self.panel.speed=3;self.panel.edit(0,10)
        self.panel.confirm();self.panel.confirm()
        self.panel.commanded=self.panel.next_step()
        with patch('robot.panel_core.time.monotonic',return_value=100):
            self.assertIsNone(self.panel.next_step())
        with patch('robot.panel_core.time.monotonic',return_value=102):
            self.assertIsNone(self.panel.next_step())
        self.assertTrue(self.panel.stopped)

    def test_runtime_ack_releases_step_without_claiming_arrival(self):
        import json, threading
        from types import SimpleNamespace
        from robot.panel_transport import Studio
        b=Studio.__new__(Studio);b.lock=threading.RLock()
        b.closed=False;b.capable=True;b.error=None
        target={k:0.0 for k in KEYS};target[KEYS[3]]=0.25
        b.pending=target;b.trace_path=None
        def receive():
            b.closed=True
            return json.dumps({'event':'observation','data':{k:0.0 for k in KEYS},'actions':target})
        b.ws=SimpleNamespace(recv=receive)
        b._receive()
        self.assertIsNone(b.pending)
        self.assertEqual(b.values[KEYS[3]],0)
