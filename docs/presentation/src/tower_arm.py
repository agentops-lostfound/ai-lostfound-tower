import sys;sys.path.insert(0,'.')
from ik import *
S_,PX,BX,BY=1.45,38.84,1290,560
def tgt(sx,sy,z): return [PX+(BY-sy)/S_,(BX-sx)/S_,z]
x=np.array([0,0,0,60.]); P={}
for n,t in [('r4h',tgt(1547,256,75)),('r4p',tgt(1547,256,18)),('bxh',tgt(1290,78,72)),('bxp',tgt(1290,78,28))]:
    x,e=solve(t,x); P[n]=x
P["home"]=np.array([-40,-100,96,40.])
OPEN,CLOSE=35.0,2.0
way=[(0,'home',OPEN),(8,'home',OPEN),(22,'r4h',OPEN),(30,'r4p',OPEN),(35,'r4p',CLOSE),(44,'r4h',CLOSE),(60,'bxh',CLOSE),(66,'bxp',CLOSE),(72,'bxp',CLOSE),(73,'bxp',OPEN),(78,'bxh',OPEN),(92,'home',OPEN),(100,'home',OPEN)]
ease=lambda u:u*u*(3-2*u)
def at(t):
    for (a,pa,ga),(b,pb,gb) in zip(way,way[1:]):
        if a<=t<=b:
            u=ease((t-a)/(b-a)) if b>a else 0
            return P[pa]+(P[pb]-P[pa])*u, ga+(gb-ga)*((t-a)/(b-a))
def simp(h,amin=14):
    h=list(h)
    while len(h)>4:
        best=None
        for i in range(len(h)):
            a,b,c=h[i-1],h[i],h[(i+1)%len(h)]
            ar=abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2
            if best is None or ar<best[0]: best=(ar,i)
        if best[0]>amin: break
        h.pop(best[1])
    return h
groups={}
for g in S['geoms']: groups.setdefault((g['body'],g['kind']),[]).extend(g['pts'])
groups={k:np.array(v) for k,v in groups.items()}
def frame(t,bodies=None):
    q,gr=at(t); qd=dict(zip(J,q)); qd['gripper']=gr; tf=fk(qd)
    pcs=[]
    for (b,k),pts in groups.items():
        if bodies=='base' and b!=0: continue
        if bodies is None and b==0: continue
        R,p=tf[b]; W=(R@pts.T).T+p
        sx=BX-S_*W[:,1]; sy=BY-S_*(W[:,0]-PX)
        h=simp(hull([(round(a),round(c)) for a,c in zip(sx,sy)]))
        if len(h)<3: continue
        pcs.append((W[:,2].mean(),k,h))
    pcs.sort(key=lambda z:z[0])
    out=''.join(f'<path class="{ "m" if k=="motor" else ("c" if k=="camera" else "p")}" d="M'+'L'.join(f'{a} {c}' for a,c in h)+'Z"/>' for _,k,h in pcs)
    held=35<=t<72
    if held and bodies is None:
        T=tip(tf); sx=BX-S_*T[1]; sy=BY-S_*(T[0]-PX)
        out+=f'<rect x="{sx-9:.0f}" y="{sy-26:.0f}" width="18" height="52" rx="3" fill="url(#bl)"/>'
    return out
N=36; CYC=10
frames=[frame(i*100/N) for i in range(N)]
css=(".p{fill:#fff;stroke:#6b7684;stroke-width:1.6;stroke-linejoin:round}.m{fill:#23262d;stroke:#0d0f12;stroke-width:1}.c{fill:#3d4450;stroke:#0d0f12}"
     f"g.k{{visibility:hidden;animation:fr {CYC}s step-end infinite}}@keyframes fr{{0%{{visibility:visible}}{100/N:.2f}%{{visibility:hidden}}100%{{visibility:hidden}}}}")
grad='<defs><linearGradient id="bl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#E3264E"/><stop offset=".66" stop-color="#C4173C"/><stop offset=".66" stop-color="#fff"/><stop offset="1" stop-color="#E6E7EA"/></linearGradient></defs>'
import embeds
chunks=[];cur=[];size=0
for i,f in enumerate(frames):
    g=f'<g class="k" style="animation-delay:{i*CYC/N:.2f}s">{f}</g>'
    if size+len(g.encode())>13900: chunks.append(cur);cur=[];size=0
    cur.append(g);size+=len(g.encode())
chunks.append(cur)
def embeds_out():
    base=frame(0,'base')
    return [embeds.wrap(864,650,css,f'<svg width="1664" height="650" style="position:absolute;left:-800px;top:0;filter:drop-shadow(5px 8px 5px rgba(22,32,46,.25))">{grad}{base if j==0 else ""}{"".join(c)}</svg>') for j,c in enumerate(chunks)]
if __name__=='__main__':
    E=embeds_out(); print(len(E),[len(e.encode()) for e in E], [len(f) for f in frames[:3]])
