"""Convert existing Studio pose files to the installed LeRobot degree convention."""
import math
from robot.joint_motion import JOINTS, vector


class VendorCoordinates:
    def __init__(self,calibration):
        self.calibration=calibration
        for name in JOINTS:
            c=calibration[name]
            if c['drive_mode']!=0 or c['range_max']<=c['range_min']:
                raise ValueError('Unsupported calibration for '+name)

    def degrees(self,normalized):
        vector(normalized)
        result={}
        for name in JOINTS:
            key=name+'.pos';value=normalized[key];c=self.calibration[name]
            if name=='gripper':result[key]=value;continue
            tick=round(c['range_min']+(value+100)/200*(c['range_max']-c['range_min']))
            result[key]=(tick-(c['range_min']+c['range_max'])/2)*360/4095
        return result

    def normalized(self,degrees):
        result={}
        for name in JOINTS:
            key=name+'.pos';value=float(degrees[key]);c=self.calibration[name]
            if not math.isfinite(value):raise ValueError('Nonfinite observation')
            result[key]=value if name=='gripper' else max(-100,min(100,
                value*4095/360*200/(c['range_max']-c['range_min'])))
        vector(result)
        return result
