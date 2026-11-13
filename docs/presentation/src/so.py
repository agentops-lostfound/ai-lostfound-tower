import json,math,numpy as np
S=json.load(open('shape.json'))
def qmat(q):
    w,x,y,z=q;n=math.sqrt(w*w+x*x+y*y+z*z);w,x,y,z=w/n,x/n,y/n,z/n
    return np.array([[1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)],[2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)],[2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)]])
QB=[qmat(b['quat']) for b in S['bodies']]
def rz(a): c,s=math.cos(a),math.sin(a); return np.array([[c,-s,0],[s,c,0],[0,0,1]])
def fk(q):
    out=[]
    for i,b in enumerate(S['bodies']):
        R0,p0=(np.eye(3),np.zeros(3)) if b['parent']<0 else out[b['parent']]
        R=R0@QB[i]; p=p0+R0@np.array(b['pos'])
        if b['joint']: R=R@rz(math.radians(q.get(b['joint'],0)))
        out.append((R,p))
    return out
def tip(tf): R,p=tf[S['tip']['body']]; return p+R@np.array(S['tip']['pos'])
def hull(P):
    P=sorted(set(P)); 
    if len(P)<3: return P
    cr=lambda o,a,b:(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lo=[];up=[]
    for p in P:
        while len(lo)>1 and cr(lo[-2],lo[-1],p)<=0: lo.pop()
        lo.append(p)
    for p in reversed(P):
        while len(up)>1 and cr(up[-2],up[-1],p)<=0: up.pop()
        up.append(p)
    return lo[:-1]+up[:-1]
