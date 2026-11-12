import sys;sys.path.insert(0,'.')
from so import *
from scipy.optimize import minimize
J=['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex']
RNG={b['joint']:b['range'] for b in S['bodies'] if b['joint']}
def solve(target,x0):
    T=np.array(target)
    def cost(v):
        q=dict(zip(J,v)); tf=fk(q); t=tip(tf); g=tf[5][1]
        c=np.sum((t-T)**2)+0.5*np.sum((g[:2]-t[:2])**2)+ (0 if g[2]>t[2] else 1e4)
        return c
    r=minimize(cost,x0,method='L-BFGS-B',bounds=[RNG[j] for j in J])
    return r.x, math.sqrt(r.fun)
HOME=np.array([0,-100,96,70.0])
