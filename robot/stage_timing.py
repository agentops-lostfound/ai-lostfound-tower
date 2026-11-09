"""Wall-clock pacing for a vendor trajectory, with a five-second command deadline."""
import math
import time


class StageClock:
    def __init__(self,duration=5.0,clock=time.monotonic,sleep=time.sleep):
        if not math.isfinite(duration) or duration<=0:raise ValueError('Positive finite duration required')
        self.duration=min(duration,5.0)
        self.clock=clock;self.sleeper=sleep;self.started=clock();self.next_wake=self.started

    def check(self):
        if self.clock()-self.started>=self.duration-1e-9:
            raise TimeoutError('Stage command deadline reached (maximum 5 seconds)')

    def sleep(self,seconds):
        self.next_wake+=seconds
        remaining=min(self.next_wake,self.started+self.duration)-self.clock()
        if remaining>0:self.sleeper(remaining)
