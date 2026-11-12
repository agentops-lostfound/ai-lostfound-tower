"""SO101 URDF FK/IK 모델 계산. 실제 서보 각도 정합 및 이동과 분리."""
import hashlib
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np

MODEL=Path(__file__).parent/'assets/so101_follower.urdf'
NAMES=['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll']


def rotation(axis,angle):
    a=np.asarray(axis,float);a/=np.linalg.norm(a)
    x,y,z=a;k=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    return np.eye(3)+math.sin(angle)*k+(1-math.cos(angle))*(k@k)


class Model:
    def __init__(self,opening_axis_local=None,*,use_position_calibration=True):
        self.opening_axis_local=np.asarray([1,0,0] if opening_axis_local is None else opening_axis_local,float)
        if self.opening_axis_local.shape!=(3,) or not np.isclose(np.linalg.norm(self.opening_axis_local),1):raise ValueError('집게 벌림 축 단위벡터 필요')
        root=ET.parse(MODEL).getroot();joints={j.attrib['name']:j for j in root.findall('joint')}
        self.chain=[];self.limits=[]
        for name in NAMES+['gripper_frame_joint']:
            j=joints[name];origin=j.find('origin');xyz=np.fromstring(origin.attrib['xyz'],sep=' ')*1000
            r,p,y=np.fromstring(origin.attrib['rpy'],sep=' ')
            transform=np.eye(4);transform[:3,:3]=rotation([0,0,1],y)@rotation([0,1,0],p)@rotation([1,0,0],r);transform[:3,3]=xyz
            axis=np.fromstring(j.find('axis').attrib['xyz'],sep=' ')
            self.chain.append((name,transform,axis))
            if name in NAMES:
                limit=j.find('limit');self.limits.append([float(limit.attrib['lower']),float(limit.attrib['upper'])])
        self.limits=np.asarray(self.limits)
        self.hash=hashlib.sha256(MODEL.read_bytes()).hexdigest()
        self.base_offset=self.chain[0][1][:3,3]*[1,1,0]
        self.position_calibration=None
        if use_position_calibration:
            from .tcp_calibration import active_profile
            self.position_calibration=active_profile(self.hash)

    def forward(self,q,*,with_points=True):
        q=np.asarray(q,float)
        if q.shape!=(5,) or not np.isfinite(q).all(): raise ValueError('5개 모델 관절각(rad)이 필요합니다.')
        t=np.eye(4);points=[(-self.base_offset).tolist()] if with_points else []
        for i,(name,origin,axis) in enumerate(self.chain):
            t=t@origin
            if with_points:points.append((t[:3,3]-self.base_offset).tolist())
            if i<5:
                turn=np.eye(4);turn[:3,:3]=rotation(axis,q[i]);t=t@turn
        position=t[:3,3]-self.base_offset
        if self.position_calibration:
            base=np.asarray(self.position_calibration['base_translation_mm'])
            position=position+base+t[:3,:3]@self.position_calibration['tcp_local_mm']
            points=[(np.asarray(p)+base).tolist() for p in points]
            if with_points:points.append(position.tolist())
        return {'position':position,'tool_axis':t[:3,2],'opening_axis':t[:3,:3]@self.opening_axis_local,'points':points,'rotation':t[:3,:3]}

    def residual(self,q,target,down=True):
        fk=self.forward(q,with_points=False);r=fk['position']-target
        if down:r=np.r_[r,60*(fk['tool_axis']-[0,0,-1])]
        return r

    def inverse(self,target,seed=None,tool_down=False,fixed_roll=None,prefer_seed=False,opening_yaw=None,orientation_weight=60,down_weight=60,max_down_deg=5):
        target=np.asarray(target,float)
        if target.shape!=(3,) or not np.isfinite(target).all() or np.max(np.abs(target))>1000:
            raise ValueError('유효한 모델 목표 X,Y,Z(mm)가 필요합니다.')
        seeds=[np.zeros(5),np.array([0,.7,-1.1,.5,0]),np.array([0,-.7,1.1,-.5,0])]
        if seed is not None:seeds.insert(0,np.asarray(seed,float))
        variables=range(5) if fixed_roll is None else range(4)
        if fixed_roll is not None and not self.limits[4,0]<=fixed_roll<=self.limits[4,1]:raise ValueError('손목 회전 목표가 모델 범위 밖입니다.')
        def residual(q,target,down):
            fk=self.forward(q,with_points=False)
            result=fk['position']-target
            if down:result=np.r_[result,down_weight*(fk['tool_axis']-[0,0,-1])]
            if opening_yaw is not None:
                axis=np.array([math.cos(opening_yaw),math.sin(opening_yaw),0.])
                result=np.r_[result,orientation_weight*(fk['opening_axis']-axis)]
            return result
        best=None;best_rank=None
        for initial in seeds:
            q=np.clip(initial,self.limits[:,0],self.limits[:,1])
            if fixed_roll is not None:q[4]=fixed_roll
            for _ in range(140):
                r=residual(q,target,tool_down)
                jac=np.column_stack([(residual(q+np.eye(5)[i]*1e-5,target,tool_down)-r)/1e-5 for i in variables])
                partial=np.linalg.solve(jac.T@jac+np.eye(len(variables))*2,jac.T@r)
                step=np.zeros(5);step[list(variables)]=partial
                norm=np.linalg.norm(step)
                if norm>.2:step*=.2/norm
                current=np.linalg.norm(r);accepted=False
                for scale in [1,.5,.2,.05]:
                    candidate=np.clip(q-step*scale,self.limits[:,0],self.limits[:,1])
                    if np.linalg.norm(residual(candidate,target,tool_down))<current:
                        q=candidate;accepted=True;break
                if not accepted or current<.001:break
            error=float(np.linalg.norm(residual(q,target,tool_down)))
            fk_candidate=self.forward(q,with_points=False)
            pos_error=float(np.linalg.norm(fk_candidate['position']-target))
            down_angle=float(np.degrees(np.arccos(np.clip(-fk_candidate['tool_axis'][2],-1,1))))
            feasible=pos_error<3 and (not tool_down or down_angle<max_down_deg)
            rank=(0 if feasible else 1,float(np.linalg.norm(q-np.asarray(seed)))) if prefer_seed and seed is not None and feasible else (1,error)
            if best is None or rank<best_rank:best=(error,q);best_rank=rank
        _,q=best;fk=self.forward(q)
        error=float(np.linalg.norm(fk['position']-target))
        angle=float(np.degrees(np.arccos(np.clip(fk['tool_axis']@[0,0,-1],-1,1))))
        return {'joint_radians':q.tolist(),'joint_degrees':np.degrees(q).tolist(),
            'position_mm':fk['position'].tolist(),'position_error_mm':error,'tool_down_error_deg':angle,
            'reachable_in_model':error<3 and (not tool_down or angle<max_down_deg),'tool_down_required':tool_down,'points_mm':fk['points']}


def preview(point, height, tool_down=False):
    from .robot_frame import transform
    measured=transform(point,height)
    model=Model();target=measured['approach_mm']
    solved=model.inverse(target,tool_down=tool_down)
    q=np.asarray(solved['joint_radians'])
    # Simulation starts at model zero, NOT the real arm's current position.
    path=[]
    for t in np.linspace(0,1,41):
        blend=10*t**3-15*t**4+6*t**5
        pose=q*blend
        path.append({'joint_radians':pose.tolist(),'points_mm':model.forward(pose)['points']})
    return {'measured_target':measured,'model_result':solved,'joint_names':NAMES,'model_sha256':model.hash,
        'assumptions':['측정한 전방과 URDF +X가 일치한다고 임시 가정','회전축의 책상 투영점을 원점으로 사용','URDF gripper_frame_link를 임시 집게 기준점으로 사용'],
        'hardware_alignment':'unverified','motion_sent':False,'robot_ready':False,
        'simulation_start':'model_zero_not_hardware','simulation_path':path,'collision_checked':False,
        'blockers':['실제 관절각 영점·회전 방향 미검증','측정 좌표와 모델 좌표 방향 미검증','집게 기준점(TCP)·이동 경로 충돌 미검증']}
