"""Position-only URDF IK experiment. Model radians only; no robot transport."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np


def rotation(axis, angle):
    axis=np.asarray(axis,dtype=float)
    norm=np.linalg.norm(axis)
    if norm<1e-12:raise ValueError('Invalid joint axis')
    x,y,z=axis/norm
    k=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    return np.eye(3)+math.sin(angle)*k+(1-math.cos(angle))*(k@k)


class Model:
    def __init__(self,path,tip='gripper_frame_link',base='base_link'):
        raw=Path(path).read_bytes()
        self.sha256=hashlib.sha256(raw).hexdigest()
        root=ET.fromstring(raw)
        by_child={j.find('child').get('link'):j for j in root.findall('joint')}
        chain=[];link=tip;seen=set()
        while link!=base:
            if link in seen or link not in by_child:raise ValueError('No valid base to tip chain')
            seen.add(link);j=by_child[link];chain.append(j);link=j.find('parent').get('link')
        self.chain=[];self.names=[];limits=[]
        for j in reversed(chain):
            kind=j.get('type')
            if kind not in ('fixed','revolute'):raise ValueError('Unsupported joint type')
            origin=j.find('origin')
            xyz=np.fromstring(origin.get('xyz','0 0 0') if origin is not None else '0 0 0',sep=' ')
            rpy=np.fromstring(origin.get('rpy','0 0 0') if origin is not None else '0 0 0',sep=' ')
            if len(xyz)!=3 or len(rpy)!=3:raise ValueError('Invalid joint origin')
            t=np.eye(4);t[:3,3]=xyz
            t[:3,:3]=rotation([0,0,1],rpy[2])@rotation([0,1,0],rpy[1])@rotation([1,0,0],rpy[0])
            axis=j.find('axis');a=np.fromstring(axis.get('xyz') if axis is not None else '1 0 0',sep=' ')
            self.chain.append((kind,t,a))
            if kind=='revolute':
                lim=j.find('limit');lo=float(lim.get('lower'));hi=float(lim.get('upper'))
                if not math.isfinite(lo+hi) or lo>=hi:raise ValueError('Invalid joint limits')
                self.names.append(j.get('name'));limits.append([lo,hi])
        self.limits=np.array(limits);self.base=base;self.tip=tip
        if not limits:raise ValueError('No movable joints')

    def fk(self,q):
        q=np.asarray(q,dtype=float)
        if q.shape!=(len(self.names),) or not np.isfinite(q).all():raise ValueError('Invalid joint vector')
        t=np.eye(4);i=0
        for kind,origin,axis in self.chain:
            t=t@origin
            if kind=='revolute':
                r=np.eye(4);r[:3,:3]=rotation(axis,q[i]);t=t@r;i+=1
        return t

    def solve(self,target_mm,tolerance_mm=1.0):
        target=np.asarray(target_mm,dtype=float)/1000
        if target.shape!=(3,) or not np.isfinite(target).all():raise ValueError('Expected finite base XYZ mm')
        lo,hi=self.limits.T;rng=np.random.default_rng(0);best=None
        for seed in [np.clip(np.zeros(len(lo)),lo,hi),*(rng.uniform(lo,hi) for _ in range(16))]:
            q=seed.copy()
            for _ in range(250):
                p=self.fk(q)[:3,3];error=target-p;distance=float(np.linalg.norm(error))
                if best is None or distance<best[0]:best=(distance,q.copy())
                if distance*1000<=tolerance_mm:break
                jac=np.column_stack([(self.fk(q+np.eye(len(q))[i]*1e-5)[:3,3]-p)/1e-5 for i in range(len(q))])
                step=jac.T@np.linalg.solve(jac@jac.T+np.eye(3)*1e-5,error)
                q=np.clip(q+np.clip(step,-0.2,0.2),lo,hi)
            if best[0]*1000<=tolerance_mm:break
        distance,q=best
        return {'schema':'offline_ik.v1','status':'position_solution' if distance*1000<=tolerance_mm else 'no_solution_found',
                'base_link':self.base,'tip_link':self.tip,'target_base_xyz_mm':list(target_mm),
                'joint_unit':'urdf_radians','joints':dict(zip(self.names,q.tolist())),
                'fk_xyz_mm':(self.fk(q)[:3,3]*1000).tolist(),'position_error_mm':distance*1000,
                'model_sha256':self.sha256,'robot_authorized':False,
                'limitations':['position_only','orientation_unconstrained','collision_not_checked',
                               'installation_to_base_unverified','motor_zero_mapping_unverified']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--urdf',type=Path,required=True)
    p.add_argument('--base-xyz-mm',type=float,nargs=3,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=Model(a.urdf).solve(a.base_xyz_mm)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps(r,indent=2))


if __name__=='__main__':main()
