"""관제탑 가상 팔(공식 SO-101 모양) — 부품 윤곽을 CSS d:path() 키프레임으로 부드럽게 움직임"""
import sys;sys.path.insert(0,'.')
import numpy as np, math
from ik import *
import tower_arm as TA          # 자세(P), 시간표(way), at(t) 재사용
import embeds
K=9
# 실물 티칭 순서(11단계, 단계마다 움직임 50% + 멈춤 50%, 실물 44초의 약 80% 속도): 원점 → pose_7 칸 위 → 열기 → 내려감 → 닫기 → 들기 → 제출보관함 위 → 내림 → 열기 → 들기 → 원점
SEQ=[('home',15),('r4h',15),('r4h',35),('r4p',35),('r4p',2),('r4h',2),('bxh',2),('bxp',2),('bxp',35),('bxh',35),('home',15)]
D=100/11
TA.P['home']=np.array([0,-100,96,40.])  # 원점: 사선이 아니라 세로(정면) 방향
TA.way=[(0,'home',15)]
for i in range(1,11):
    TA.way+=[(round(i*D,2),)+SEQ[i-1],(round(i*D+0.5*D,2),)+SEQ[i]]
TA.way+=[(100,'home',15)]
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
        q,gr=TA.at(t); qd=dict(zip(J,q)); qd['gripper']=gr
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
def side_embed(W_,H_,s,ox,gy,dark,labels,pfx,cyc,show_held=True):
    PX=TA.PX
    proj=lambda W:np.c_[ox+s*(W[:,0]-PX),gy-s*W[:,2],-W[:,1]]
    pcs,tips=build(proj,pan0=True,skip_base=False)
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
    chs=split(pcs,10000); out=[]
    for j,ch in enumerate(chs):
        c2,b2=svg_css(ch,cyc,pfx+str(j),dark)
        first,last=j==0,j==len(chs)-1
        out.append(((css if first else '')+c2+(hc if last else ''), (pre if first else '')+f'<svg width="{W_}" height="{H_}" style="position:absolute;left:0;top:0">{b2}</svg>'+(hh if last else '')))
    return out

def side4():
    ch=side_embed(288,176,0.5,62,150,False,True,'s',CYC,show_held=False); out=[]
    for j,(c,h) in enumerate(ch):
        bg='<div style="position:absolute;left:0;top:0;width:288px;height:176px;border-radius:16px;background:#fff;border:2px solid #E3D6C4;box-sizing:border-box"></div>' if j==0 else ''
        cap='<p style="position:absolute;left:12px;top:154px;margin:0;font-size:15px;font-weight:800;color:#B5500A">옆에서 본 모습</p>' if j==len(ch)-1 else ''
        out.append(embeds.wrap(288,176,c,bg+h+cap))
    return out
def side14():
    from embeds import ACCL
    ch=side_embed(260,150,0.5,58,132,False,False,'r',36); out=[]
    for j,(c,h) in enumerate(ch):
        lab=(f'<div style="position:absolute;left:10px;top:10px;padding:5px 10px;border-radius:10px;background:#16202E;color:{ACCL};font-size:17px;font-weight:800;white-space:nowrap">R4-1 → pose_7</div>') if j==len(ch)-1 else ''
        out.append(embeds.wrap(260,150,c,h+lab))
    return out
