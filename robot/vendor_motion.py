"""One vendor motion with cancellation and five-second wall-clock pacing."""
import math
from types import SimpleNamespace
from robot.stage_timing import StageClock


def move_stage(robot,target,*,duration=5,cancelled=lambda:False,observe=lambda *args:None,
               vendor=None,timer=None,include_gripper=False):
    if vendor is None:from so101_control import control as vendor
    if not math.isfinite(duration) or not 0<duration<=5:
        raise ValueError('Stage duration must be in (0, 5] seconds')
    current=robot.get_observation()
    target=dict(target)
    if not include_gripper:target['gripper.pos']=current['gripper.pos']
    timer=timer or StageClock(duration)

    class Sender:
        def send_action(self,action):
            timer.check()
            if cancelled():raise InterruptedError('Operator stop or GUI disconnected')
            applied=robot.send_action(action)
            observe(action,applied)

    original_time=vendor.time
    vendor.time=SimpleNamespace(sleep=timer.sleep)
    try:
        # Reach the final command before the deadline, then let the physical servo
        # settle at that goal. Freezing the measurement immediately would cut it short.
        trajectory_seconds=max(1/30,duration*0.8-1/30)
        vendor.move_to_joints(Sender(),target,current=current,
                              duration_s=trajectory_seconds,fps=30)
        while True:
            if cancelled():raise InterruptedError('Operator stop or GUI disconnected')
            remaining=timer.started+duration-timer.clock()
            if remaining<=1e-9:break
            timer.sleeper(min(0.02,remaining))
        return robot.get_observation()
    finally:
        vendor.time=original_time
        # Freeze once at the measured position, also on stop/deadline/error.
        robot.send_action(robot.get_observation())
