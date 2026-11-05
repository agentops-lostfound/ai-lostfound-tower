import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from robot.joint_motion import JOINTS
from robot.panel_core import KEYS, Panel
from robot.vendor_backend import VendorBackend
from robot.vendor_backend import STAGE_SECONDS
from robot.vendor_coordinates import VendorCoordinates
from robot.vendor_motion import move_stage


class VendorTests(unittest.TestCase):
    def test_duration_levels_include_time_for_servo_settling(self):
        from robot.stage_timing import StageClock
        self.assertEqual(STAGE_SECONDS,{1:5.0,2:4.0,3:3.0})
        now=[0.0];goal={k:0.0 for k in KEYS};goal[KEYS[0]]=10
        robot=SimpleNamespace(values={k:0.0 for k in KEYS})
        holds=[]
        robot.get_observation=lambda:dict(robot.values)
        def send(action):
            holds.append((now[0],dict(action)))
            robot.goal=dict(action)
        robot.send_action=send
        def sleep(seconds):
            now[0]+=seconds
            if now[0]>=2.9:robot.values=dict(robot.goal)
        timer=StageClock(3,clock=lambda:now[0],sleep=sleep)
        def move(sender,target,**kwargs):
            self.assertLess(kwargs['duration_s'],2.4)
            now[0]=2.4;sender.send_action(target)
        vendor=SimpleNamespace(time=object(),move_to_joints=move)
        result=move_stage(robot,goal,duration=3,vendor=vendor,timer=timer)
        self.assertAlmostEqual(now[0],3)
        self.assertEqual(result[KEYS[0]],10)
        self.assertEqual(holds[-1][1][KEYS[0]],10)

    def test_saved_pose_converts_via_encoder_ticks(self):
        calibration={n:{'drive_mode':0,'range_min':900,'range_max':3300} for n in JOINTS}
        c=VendorCoordinates(calibration)
        norm={k:30.0 for k in KEYS};norm['gripper.pos']=4
        degree=c.degrees(norm)
        self.assertAlmostEqual(degree['elbow_flex.pos'],360*360/4095)
        self.assertEqual(degree['gripper.pos'],4)
        restored=c.normalized(degree)
        self.assertAlmostEqual(restored['elbow_flex.pos'],30)

    def test_stop_during_vendor_loop_holds_and_restores_time(self):
        robot=SimpleNamespace(values={k:0.0 for k in KEYS})
        sent=[]
        robot.get_observation=lambda:dict(robot.values)
        def send(action):robot.values=dict(action);sent.append(dict(action))
        robot.send_action=send
        original_time=object()
        def vendor_move(sender,target,**kwargs):
            sender.send_action(dict(target))
            sender.send_action(dict(target))
        vendor=SimpleNamespace(time=original_time,move_to_joints=vendor_move)
        target={k:2.0 for k in KEYS};robot.values['gripper.pos']=4
        with self.assertRaises(InterruptedError):
            move_stage(robot,target,vendor=vendor,cancelled=lambda:len(sent)>0,
                       timer=SimpleNamespace(check=lambda:None,sleep=lambda _:None))
        self.assertIs(vendor.time,original_time)
        self.assertEqual(len(sent),2)  # one movement command plus measured hold
        self.assertEqual(sent[0]['gripper.pos'],4)
        self.assertEqual(sent[-1],robot.values)

    def test_worker_error_and_result_do_not_imply_arrival(self):
        backend=VendorBackend.__new__(VendorBackend)
        backend.lock=threading.RLock();backend.pending=7;backend.result=None;backend.busy=True
        backend._accept({'event':'result','id':7,'completed':True,'error':None,
                         'errors_degrees':{'elbow_flex.pos':8}})
        self.assertFalse(backend.busy);self.assertIsNone(backend.pending)
        self.assertEqual(backend.result['errors_degrees']['elbow_flex.pos'],8)


class StageGUIBackend:
    live=True;stage_motion=True;name='test vendor';mode='hold';error=None;failure=None
    def __init__(self):
        self.values={k:0.0 for k in KEYS};self.pending=None;self.result=None;self.busy=False
        self.started=[];self.repaired=False
    def snapshot(self):return dict(self.values)
    def fresh(self):return True
    def ready(self):return self.repaired and not self.busy
    def repair(self):self.repaired=True
    def stop(self):self.busy=False;self.pending=None
    def close(self):pass
    def start_stage(self,target,expected,level):
        self.started.append((dict(target),dict(expected),level));self.busy=True;self.pending=1


class VendorGUITests(unittest.TestCase):
    def test_buttons_use_whole_vendor_stage_and_persist_measured_pose(self):
        import tkinter as tk
        from robot.teaching_gui import TeachingGUI
        with tempfile.TemporaryDirectory() as folder:
            try:root=tk.Tk()
            except tk.TclError as exc:self.skipTest(str(exc))
            root.withdraw()
            try:
                backend=StageGUIBackend();panel=Panel(folder)
                gui=TeachingGUI(root,panel,backend,Path(folder),SimpleNamespace(close=lambda:None))
                # The old movement function must never be called on the vendor GUI path.
                panel.next_step=lambda:(_ for _ in ()).throw(AssertionError('Legacy motion used'))
                with patch('robot.teaching_gui.messagebox.askyesno',return_value=True):
                    gui._tick();gui._repair()
                    gui._jog(0,1);gui._review();gui._review()
                    self.assertEqual(backend.started,[])
                    gui._approve();self.assertEqual(len(backend.started),1)
                    gui._tick();self.assertTrue(panel.moving)
                    backend.values[KEYS[0]]=0.08
                    backend.busy=False;backend.pending=None
                    backend.result={'completed':True,'errors_degrees':{KEYS[0]:0.2}}
                    gui._tick();self.assertFalse(panel.moving)
                    self.assertIn('residual',gui.status_text.get())
                    gui.pose_name.set('custom');gui._save()
                    self.assertEqual(Panel(folder).poses['custom'][KEYS[0]],0.08)
                    gui._jog(0,1);gui._review();gui._approve();gui._stop()
                    self.assertTrue(panel.stopped);self.assertFalse(panel.moving)
            finally:root.destroy()
