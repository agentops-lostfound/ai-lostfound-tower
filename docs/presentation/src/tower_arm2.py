"""관제탑 가상 팔(공식 SO-101 모양) — 부품 윤곽을 CSS d:path() 키프레임으로 부드럽게 움직임"""
import sys;sys.path.insert(0,'.')
import numpy as np, math
from ik import *
import tower_arm as TA          # 자세(P), 시간표(way), at(t) 재사용
import embeds
K=9
# 실물 티칭 순서(11단계, 단계마다 움직임 50% + 멈춤 50%, 실물 44초의 약 80% 속도): 원점 → pose_7 칸 위 → 열기 → 내려감 → 닫기 → 들기 → 제출보관함 위 → 내림 → 열기 → 들기 → 원점
SEQ=[('home',-5),('r4h',15),('r4h',35),('r4p',35),('r4p',2),('r4h',2),('bxh',2),('bxp',2),('bxp',35),('bxh',35),('home',-5)]
D=100/11
# 원점 = 실물 home(접힌 대기 자세): robot/config/home_pose.json · outputs/robot_panel_live/poses.json 'home'
# (Studio normalized 값을 각도로 보고 관절 한계로 자름 — 관제탑 agents/sim_world.py REST_JOINTS 와 같은 방식)
TA.P['home']=np.array([-3.8,-99.4,96.8,-95.0])
REST_ROLL,REST_GRIP=9.9,-5.0
TA.way=[(0,'home',-5)]
for i in range(1,11):
    TA.way+=[(round(i*D,2),)+SEQ[i-1],(round(i*D+0.5*D,2),)+SEQ[i]]
TA.way+=[(100,'home',-5)]
TS=sorted(set([0,100]+[round(i*D,2) for i in range(1,11)]+[round(i*D+0.5*D,2) for i in range(1,11)]+[round(i*D+0.25*D,2) for i in (1,6,10)]))
T_PICK=round(4*D+0.5*D,2); T_REL=round(8*D+0.25*D,2)
GR={}
for g in S['geoms']: GR.setdefault((g['body'],g['kind']),[]).extend(g['pts'])
GR={k:np.array(v) for k,v in GR.items()}
def resample(h,ref):
    h=np.array(h,float)
    if len(h)<3: h=np.vstack([h,h+0.1,h+0.2])
    i0=int(np.argmin(np.sum((h-ref)**2,1))); h=np.roll(h,-i0,0)
    seg=np.vstack([h,h[:1]]); L=np.r_[0,np.cumsum(np.hypot(*np.diff(seg,axis=0).T))]
    out=[]
    for d in np.linspace(0,L[-1],K,endpoint=False):
        j=min(np.searchsorted(L,d,side='right')-1,len(h)-1); u=(d-L[j])/max(L[j+1]-L[j],1e-6)
        out.append(seg[j]+(seg[j+1]-seg[j])*u)
    return np.round(out).astype(int)
def build(proj,pan0=False,skip_base=True):
    """proj(W3)->(x,y,depth). 반환: [(kind, [(t,'M..Z')...], 평균깊이)], tip 경로"""
    pieces={k:[] for k in GR if not (skip_base and k[0]==0)}; depth={k:0 for k in pieces}; tips=[]
    for t in TS:
        q,gr=TA.at(t); qd=dict(zip(J,q)); qd['gripper']=gr; qd['wrist_roll']=REST_ROLL
        if pan0: qd['shoulder_pan']=0
        tf=fk(qd)
        for k in pieces:
            R,p=tf[k[0]]; W=(R@GR[k].T).T+p; xy=proj(W)
            ref=proj((R@GR[k][:1].T).T+p)[0]
            h=hull([tuple(v) for v in np.round(xy[:,:2]).astype(int)])
            pts=resample(h,ref[:2]); pieces[k].append((t,'M'+'L'.join(f'{a} {b}' for a,b in pts)+'Z')); depth[k]+=W[:,2].mean()
        tips.append((t,proj(tip(tf)[None])[0]))
    order=sorted(pieces,key=lambda k:depth[k])
    return [(k[1],pieces[k]) for k in order],tips
def svg_css(pieces,cyc,pfx,dark=False):
    css=""; body=""
    for i,(kind,fr) in enumerate(pieces):
        n=f"{pfx}{i}"
        css+="@keyframes %s{%s}"%(n,"".join('%s%%{d:path("%s")}'%(t,d) for t,d in fr))
        cl={'motor':'m','camera':'c'}.get(kind,'p')
        body+=f'<path class="{cl}" d="{fr[0][1][2:]}" style="animation:{n} {cyc}s linear infinite"/>'.replace(f'd="{fr[0][1][2:]}"',f'd="{fr[0][1]}"')
    pc="#e9edf3" if dark else "#fff"
    css+=(f".p{{fill:{pc};stroke:#6b7684;stroke-width:1.4;stroke-linejoin:round}}.m{{fill:#23262d;stroke:#0d0f12;stroke-width:1}}.c{{fill:#3d4450;stroke:#0d0f12}}")
    return css,body
def held(tips,cyc,name,w,h,lie=False):
    css="@keyframes %s{%s}"%(name,"".join("%s%%{transform:translate(%dpx,%dpx);opacity:%d}"%(t,x-w/2,y-h/2,1 if T_PICK<=t<T_REL else 0) for t,(x,y,_) in tips))
    return css,f'<div style="position:absolute;left:0;top:0;width:{w}px;height:{h}px;border-radius:2px;background:linear-gradient({'90deg,' if lie else ''}#E3264E 0 62%,#fff 62%);box-shadow:0 0 0 1px rgba(0,0,0,.25);opacity:0;animation:{name} {cyc}s linear infinite"></div>'
CYC=36
def split(pcs,lim):
    out=[[]];n=0
    for p in pcs:
        z=sum(len(d) for _,d in p[1])+60
        if n+z>lim and out[-1]: out.append([]);n=0
        out[-1].append(p);n+=z
    return out
def top_embed():
    S_,PX,BX,BY=TA.S_,TA.PX,TA.BX,TA.BY
    proj=lambda W:np.c_[BX-S_*W[:,1]-800,BY-S_*(W[:,0]-PX),W[:,2]]
    pcs,tips=build(proj)
    base,_=build(proj,skip_base=False); base=[p for p in base if p[1] and False] 
    # 받침(정지) 한 장
    q,_=TA.at(0); tf=fk(dict(zip(J,q)))
    bs=""
    for k in GR:
        if k[0]!=0: continue
        R,p=tf[0]; W=(R@GR[k].T).T+p; xy=proj(W)
        h=hull([tuple(v) for v in np.round(xy[:,:2]).astype(int)])
        bs+=f'<path class="{ {"motor":"m"}.get(k[1],"p") }" d="M'+'L'.join(f'{a} {b}' for a,b in h)+'Z"/>'
    hc,hh=held(tips,CYC,'hb',20,54)
    hc,hh='',''  # 4쪽: 집으면 립밤 안 보이게
    out=[]
    for j,ch in enumerate(split(pcs,11000)):
        css,body=svg_css(ch,CYC,'a')
        last=(j==len(split(pcs,11000))-1)
        out.append(embeds.wrap(864,650,css+(hc if last else ''),f'<svg width="864" height="650" style="position:absolute;left:0;top:0;filter:drop-shadow(5px 8px 5px rgba(22,32,46,.25))">{bs if j==0 else ""}{body}</svg>{hh if last else ""}'))
    return out
def rigid_side(s,ox,gy,pfx,cyc,dark):
    """옆모습: 관절이 화면과 수직인 축으로 돌므로 부품마다 '모양 고정 + 회전·이동'으로 그림(크기 변화 없음)"""
    PX=TA.PX
    A_of=lambda R: s*np.array([R[0],-R[2]])          # 2x3: 몸체 좌표 → 화면
    def tfs(t):
        q,gr=TA.at(t); qd=dict(zip(J,q)); qd['gripper']=gr; qd['wrist_roll']=REST_ROLL; qd['shoulder_pan']=0
        return fk(qd)
    tf0=tfs(0)
    bodies=sorted(set(k[0] for k in GR))
    css=""; body=""; depth={}; parts=[]
    keys={b:[] for b in bodies}
    for t in TS:
        tf=tfs(t)
        for b in bodies:
            R0,p0=tf0[b]; R,p=tf[b]
            A0,A=A_of(R0),A_of(R)
            M=A@np.linalg.pinv(A0)
            c0=np.array([ox+s*(p0[0]-PX),gy-s*p0[2]]); c=np.array([ox+s*(p[0]-PX),gy-s*p[2]])
            e=c-M@c0
            keys[b].append((t,"transform:matrix(%.3f,%.3f,%.3f,%.3f,%.1f,%.1f)"%(M[0,0],M[1,0],M[0,1],M[1,1],e[0],e[1])))
    for b in bodies:
        R0,p0=tf0[b]; paths=""
        for (bb,k),pts in GR.items():
            if bb!=b: continue
            W=(R0@pts.T).T+p0; xy=np.c_[ox+s*(W[:,0]-PX),gy-s*W[:,2]]
            h=TA.simp(hull([tuple(v) for v in np.round(xy).astype(int)]),3)
            cl={'motor':'m','camera':'c'}.get(k,'p')
            paths+=f'<path class="{cl}" d="M'+'L'.join(f'{a} {c}' for a,c in h)+'Z"/>'
            depth[b]=-W[:,1].mean()
        if b==0: parts.append(("",paths)); continue
        parts.append(("@keyframes %sr%d{%s}"%(pfx,b,"".join("%s%%{%s}"%(t,v) for t,v in keys[b])),
                      f'<g style="transform-box:view-box;transform-origin:0 0;animation:{pfx}r{b} {cyc}s linear infinite">{paths}</g>'))
    pc="#e9edf3" if dark else "#fff"
    base=(f".p{{fill:{pc};stroke:#6b7684;stroke-width:1.2;stroke-linejoin:round}}.m{{fill:#23262d;stroke:#0d0f12;stroke-width:1}}.c{{fill:#3d4450;stroke:#0d0f12}}")
    half=[[],[]]; n=sum(len(a)+len(b) for a,b in parts); acc=0
    for a,b in parts:
        half[0 if acc<n/2 else 1].append((a,b)); acc+=len(a)+len(b)
    return [(base+"".join(a for a,_ in h),"".join(b for _,b in h)) for h in half]
def side_embed(W_,H_,s,ox,gy,dark,labels,pfx,cyc,show_held=True):
    PX=TA.PX
    proj=lambda W:np.c_[ox+s*(W[:,0]-PX),gy-s*W[:,2],-W[:,1]]
    _,tips=build(proj,pan0=True,skip_base=False) if False else (None,None)
    tips=[(t,proj(tip(fk(dict(list(zip(J,TA.at(t)[0]))+[('gripper',TA.at(t)[1]),('wrist_roll',REST_ROLL),('shoulder_pan',0)])))[None])[0]) for t in TS]
    hc,hh=held(tips,cyc,pfx+'h',22,8,lie=True) if show_held else ('','')
    # 칸·제출보관함 위치(옆에서 본 거리)
    def tipx(n):
        q=dict(zip(J,TA.P[n])); q['shoulder_pan']=0; return ox+s*(tip(fk(q))[0]-PX)
    sx,bxx=tipx('r4p'),tipx('bxp')
    gc,pad,lc="#C9C1B3","#D6C9B5","#4A5568"
    if dark: gc,pad,lc="#4A5A70","#3A4A62","#9AA6B8"
    css=("@keyframes %sb0{0%%{opacity:1}%s%%{opacity:1}%s%%{opacity:0}97%%{opacity:0}100%%{opacity:1}}@keyframes %sb2{0%%{opacity:0}%s%%{opacity:0}%s%%{opacity:1}93%%{opacity:1}97%%{opacity:0}100%%{opacity:0}}"%(pfx,T_PICK-0.5,T_PICK,pfx,T_REL-0.5,T_REL))
    bal=lambda cx,by,a:f'<div style="position:absolute;left:{cx-11:.0f}px;top:{by-8:.0f}px;width:22px;height:8px;border-radius:2px;background:linear-gradient(90deg,#E3264E 0 62%,#fff 62%);box-shadow:0 0 0 1px rgba(0,0,0,.25);animation:{pfx}{a} {cyc}s infinite"></div>'
    pre=(f'<i style="position:absolute;left:6px;top:{gy}px;width:{W_-12}px;height:3px;background:{gc}"></i>'
         f'<i style="position:absolute;left:{sx-18:.0f}px;top:{gy-6}px;width:36px;height:6px;background:{pad}"></i>'
         f'<i style="position:absolute;left:{bxx-22:.0f}px;top:{gy-12}px;width:44px;height:12px;border:2px dashed #F06A00;border-bottom:0;box-sizing:border-box"></i>'
         +bal(sx,gy-6,'b0')+bal(bxx,gy-2,'b2'))
    if labels:
        pre+=(f'<p style="position:absolute;left:{sx-58:.0f}px;top:{gy+5}px;width:52px;margin:0;text-align:right;font-size:12px;font-weight:800;color:{lc}">R4-1</p>'
              f'<p style="position:absolute;left:{bxx-14:.0f}px;top:{gy+5}px;width:60px;margin:0;text-align:left;font-size:12px;font-weight:800;color:#B5500A">제출함</p>')
    (c1,b1),(c2,b2)=rigid_side(s,ox,gy,pfx,cyc,dark)
    out=[(css+c1, pre+f'<svg width="{W_}" height="{H_}" style="position:absolute;left:0;top:0">{b1}</svg>'),
         (c2+hc, f'<svg width="{W_}" height="{H_}" style="position:absolute;left:0;top:0">{b2}</svg>'+hh)]
    return out

def side4():
    ch=side_embed(288,176,0.5,62,150,False,True,'s',CYC,show_held=False); out=[]
    for j,(c,h) in enumerate(ch):
        bg='<div style="position:absolute;left:0;top:0;width:288px;height:176px;border-radius:16px;background:#fff;border:2px solid #E3D6C4;box-sizing:border-box"></div>' if j==0 else ''
        cap='<p style="position:absolute;left:12px;top:154px;margin:0;font-size:15px;font-weight:800;color:#B5500A">옆에서 본 모습</p>' if j==len(ch)-1 else ''
        out.append(embeds.wrap(288,176,c,bg+h+cap))
    return out
def side14():
    # 14쪽: 보관 칸과 제출 칸 사이를 넓혀 보이게(칸 r=190mm, 제출칸 r=330mm, 옆모습 전용)
    PX=TA.PX; save=dict(TA.P); x=np.array([0,0,0,60.])
    for n,(r,z) in {'r4h':(190,75),'r4p':(190,18),'bxh':(330,72),'bxp':(330,28)}.items():
        x,_=solve([PX+r,0,z],x); TA.P[n]=x
    try:
        return _side14()
    finally:
        TA.P.update(save)
def _side14():
    from embeds import ACCL
    ch=side_embed(260,150,0.5,58,132,False,False,'r',36); out=[]
    for j,(c,h) in enumerate(ch):
        lab=(f'<p style="position:absolute;left:8px;top:134px;margin:0;font-size:13px;font-weight:800;color:#B5500A;white-space:nowrap">R4-1 → pose_7</p>') if j==len(ch)-1 else ''
        out.append(embeds.wrap(260,150,c,h+lab))
    return out
