"""Exercise the actual Tk callbacks with Simulation only; never create Studio."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from robot.panel_core import Panel, KEYS
from robot.panel_transport import Simulation, Studio


class TeachingGUITests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from robot.teaching_gui import TeachingGUI
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        self.root.withdraw()
        self.panel=Panel(self.tmp.name);self.backend=Simulation()
        self.gui=TeachingGUI(self.root,self.panel,self.backend,Path(self.tmp.name),SimpleNamespace(close=lambda:None))
        self.addCleanup(self.root.destroy)
        self.dialog=patch('robot.teaching_gui.messagebox.askyesno',return_value=True)
        self.dialog.start();self.addCleanup(self.dialog.stop)
        self.gui._tick();self.gui._repair()

    def advance(self):
        for _ in range(100):
            self.gui.last_step=0;self.gui._tick()
            if not self.panel.moving:return
        self.fail('Simulation did not finish')

    def test_pose_tune_overwrite_restart_and_stop(self):
        self.gui.pose_name.set('home');self.gui._save()
        self.gui._load('home');self.gui._jog(0,1)
        self.gui._review();self.assertFalse(self.panel.moving)
        self.gui._approve();self.advance()
        self.assertIn('Target reached',self.panel.message)
        self.gui.targets[1].set('0.2');self.gui._edit(1)
        self.gui._review();self.gui._approve();self.advance()
        self.gui._save();self.gui._save_csv()
        restored=Panel(self.tmp.name)
        self.assertAlmostEqual(restored.poses['home'][KEYS[0]],0.1)
        self.assertAlmostEqual(restored.poses['home'][KEYS[1]],0.2)
        self.assertTrue(list(Path(self.tmp.name).glob('poses.backup-*.json')))
        self.gui._jog(0,1);self.gui._review();self.gui._approve()
        self.gui._stop();before=self.backend.snapshot()
        self.gui._tick();self.assertEqual(before,self.backend.snapshot())
        self.gui._repair();self.assertFalse(self.panel.moving)

    def test_repeated_review_never_moves_and_changed_input_requires_review(self):
        self.gui._jog(0,1)
        self.gui._review();self.gui._review()
        self.assertFalse(self.panel.moving)
        self.gui.targets[0].set('0.3');self.gui._tick()
        self.assertEqual(self.gui.targets[0].get(),'0.3')
        self.gui._approve();self.assertFalse(self.panel.moving)
        self.assertFalse(self.panel.confirm_pending)

    def test_nonfinite_input_cannot_be_approved(self):
        self.gui.targets[0].set('nan');self.gui._review()
        self.assertFalse(self.panel.confirm_pending)
        self.assertFalse(self.panel.moving)

    def test_routes_preview_only(self):
        for name in self.panel.sequence:self.panel.save(name)
        for direction in ('forward','reverse'):
            for _ in range(4):
                self.gui._preview_route(direction)
                self.assertFalse(self.panel.moving)

    def test_custom_buttons_load_matching_pose_without_moving_or_changing_gripper(self):
        names = [f'pose_{number}' for number in range(1, 9)]
        self.assertEqual(list(self.gui.custom_pose_buttons), names)
        before=self.backend.snapshot()
        for number, name in enumerate(names, 1):
            self.assertTrue(self.gui.custom_pose_buttons[name].instate(['disabled']))
            values={key:float(number*2+i) for i,key in enumerate(KEYS)}
            self.panel.poses[name]=values
        self.gui._refresh_pose_names()
        for name in names:
            button=self.gui.custom_pose_buttons[name]
            self.assertFalse(button.instate(['disabled']))
            button.invoke()
            self.assertEqual(self.gui.pose_name.get(),name)
            for key in KEYS[:5]:
                self.assertEqual(self.panel.target[key],self.panel.poses[name][key])
            self.assertEqual(self.panel.target[KEYS[5]],before[KEYS[5]])
            self.assertEqual(self.backend.snapshot(),before)
            self.assertFalse(self.panel.moving)
            self.assertFalse(self.panel.confirm_pending)

    def test_joint_headers_and_numeric_rows_share_visible_column_alignment(self):
        self.root.geometry('1190x800')
        self.root.deiconify()
        self.root.update()
        for column,heading in enumerate(self.gui.joint_headers):
            expected=(heading.winfo_rootx(),heading.winfo_width())
            self.assertGreater(expected[1],1)
            for row in self.gui.joint_cells:
                widget=row[column]
                self.assertEqual((widget.winfo_rootx(),widget.winfo_width()),expected)
        for row in self.gui.joint_cells:
            self.assertLess(row[1].winfo_rootx(),row[2].winfo_rootx())
            self.assertLess(row[2].winfo_rootx(),row[3].winfo_rootx())


class MotionTraceTests(unittest.TestCase):
    def test_acknowledged_but_stalled_step_times_out_and_is_logged(self):
        with tempfile.TemporaryDirectory() as folder:
            b=Studio.__new__(Studio)
            b.lock=threading.RLock();b.capable=True;b.mode='hold';b.error=None
            b.last=time.monotonic();b.pending=None;b.pending_at=0
            b.values={k:0.0 for k in KEYS};b.actions=dict(b.values)
            b.trace_path=Path(folder)/'trace.jsonl';b.command_id=0
            sent=[];b._send=lambda *args:sent.append(args)
            goal=dict(b.values);goal[KEYS[3]]=0.2
            b.step(goal,b.values)
            b.actions=dict(goal);b._trace('feedback')
            b.pending_at-=2
            self.assertFalse(b.ready())
            self.assertIn('Following timeout',b.error)
            with self.assertRaises(RuntimeError):b.step(goal,b.values)
            self.assertEqual(len(sent),1)
            rows=[json.loads(line) for line in b.trace_path.read_text().splitlines()]
            self.assertEqual([r['event'] for r in rows],['command','feedback','timeout'])
            self.assertTrue(rows[-1]['acknowledged'])
            self.assertFalse(rows[-1]['position_confirmed'])
            self.assertAlmostEqual(rows[-1]['arm_errors_normalized'][KEYS[3]],0.2)
