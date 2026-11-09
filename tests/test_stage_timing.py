import unittest
from robot.stage_timing import StageClock


class StageTimingTests(unittest.TestCase):
    def test_duration_never_exceeds_five_seconds(self):
        self.assertEqual(StageClock(40).duration,5)
        self.assertEqual(StageClock(2).duration,2)
        for value in [0,-1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):StageClock(value)

    def test_work_time_is_included_in_pacing(self):
        now=[0.0]
        timer=StageClock(clock=lambda:now[0],sleep=lambda seconds:now.__setitem__(0,now[0]+seconds))
        for _ in range(100):
            timer.check();now[0]+=0.01;timer.sleep(0.05)
        self.assertAlmostEqual(now[0],5)
        with self.assertRaises(TimeoutError):timer.check()

    def test_delayed_io_blocks_next_goal(self):
        now=[0.0];timer=StageClock(clock=lambda:now[0])
        now[0]=5.1
        with self.assertRaises(TimeoutError):timer.check()
