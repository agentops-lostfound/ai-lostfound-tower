"""Common width-based approach offset, never keyed by item/category."""
import hashlib,json,math,time
from pathlib import Path
import numpy as np
from .config import DATA
from .approach_path import SIGN
from .kinematics import MODEL


def _values(name,keys,digits):
    try:data=json.loads((DATA/name).read_text(encoding='utf8'))
    except (OSError,ValueError):return None
    return {k:np.round(np.asarray(data[k],float),digits).tolist() if isinstance(data.get(k),(list,int,float)) else data.get(k) for k in keys}


def context_key(camera=None,state=None):
    # v0.2.41 (audit C1, Fable/Codex): HARD key = only the VALUES that decide which
    # way the image gap moves (sign) - joint signs, model, opening axis, roll sign,
    # joint reference, ARM frame size. File bytes are not hashed (a re-save with a new
    # timestamp is not a change). Settings, finger registration, tcp files and joint
    # limits are reused freely. A mismatch puts the slope in 'reconfirm' (slope_state).
    # 'state' is accepted for compatibility and ignored.
    payload={'sign':SIGN.tolist(),'model':hashlib.sha256(MODEL.read_bytes()).hexdigest(),
             'orientation':_values('orientation_alignment.json',['opening_axis_local','roll_sign'],3),
             'working':_values('working_calibration.json',['reference_raw_ticks','reference_model_radians','opening_axis_local'],3)}
    if camera:payload['camera']={'frame_size':camera.get('frame_size')}
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


SUSPECT_LIMIT=2


def slope_state(key,height,frame_size,path=None):
    """Learned slope plus whether its sign must be re-confirmed before descent."""
    value=load_slope(key,height,frame_size,path)
    try:p=json.loads((path or DATA/'visual_gap_slope.json').read_text(encoding='utf8'))
    except (OSError,ValueError):p={}
    return {'slope':value,'reconfirm':value is not None and p.get('context_key')!=key,
            'suspect':int(p.get('suspect',0)),'saved_key':p.get('context_key')}


def mark_suspect(reason,path=None):
    """A reversed image response: flag the stored slope; discard it on the 2nd in a row."""
    path=path or DATA/'visual_gap_slope.json'
    try:p=json.loads(path.read_text(encoding='utf8'))
    except (OSError,ValueError):return None
    p['suspect']=int(p.get('suspect',0))+1;p['suspect_reason']=reason;p['suspect_time']=time.time()
    if p['suspect']>=SUSPECT_LIMIT:p['discarded']=True
    write(path,p);return p


def confirm_key(key,path=None):
    """Sign re-confirmed by the image under a new hard key: adopt the key, keep the value."""
    path=path or DATA/'visual_gap_slope.json'
    try:p=json.loads(path.read_text(encoding='utf8'))
    except (OSError,ValueError):return False
    if p.get('context_key')==key:return True
    p.update(previous_context_key=p.get('context_key'),context_key=key,confirmed=time.time());write(path,p);return True


def load_slope(key,height,frame_size,path=None):
    try:
        p=json.loads((path or DATA/'visual_gap_slope.json').read_text(encoding='utf8'))
        value=float(p['slope_px_per_mm'])
        # Two reversed responses in a row: the stored sign is wrong. Start again with
        # zero pre-offset and a probe move (a successful save_slope resets this).
        if p.get('discarded'):return None
        # A different context key does not discard the slope; slope_state marks it
        # 'reconfirm' and grasp_flow checks the sign on the image before descent.
        if p.get('frame_size')==list(frame_size) and math.isfinite(value) and abs(value)>=.5:
            saved=float(p['approach_height_mm'])
            if abs(saved-height)<=5:return value
            # Approach height changed (45 -> 35mm, 2026-11-11): the sign (which way the
            # image gap moves) is unchanged; scale magnitude by camera distance
            # (~height + 40mm camera offset). The gap loop re-measures it on the next move.
            if abs(saved-height)<=25:return value*(saved+40.)/(float(height)+40.)
    except (OSError,ValueError,KeyError,TypeError):pass
    return None


def save_slope(session,key,height,frame_size,trial,*,success=False,path=None):
    values=np.asarray(session.get('slopes',[]),float)
    if len(values)<(1 if success else 2) or not np.isfinite(values).all():return False
    if np.any(np.sign(values)!=np.sign(values[0])) or np.min(np.abs(values))<.5 or np.max(np.abs(values))/np.min(np.abs(values))>2.5:return False
    write(path or DATA/'visual_gap_slope.json',dict(slope_px_per_mm=float(np.median(values)),context_key=key,
          approach_height_mm=height,frame_size=list(frame_size),trial=trial,saved=time.time(),samples=len(values)))
    return True


def write(path,value):
    path=Path(path);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path)


def offset_amount(width,slope,settings,key,path=None):
    k=float(settings.get('preoffset_k',.35));c=float(settings.get('preoffset_c_mm',4));source='initial'
    try:
        fit=json.loads((path or DATA/'grasp_offset_learning.json').read_text(encoding='utf8'))
        if fit.get('fit'):
            # Offset SIZE is finger/TCP geometry and is reused under any key; the sign
            # comes from the slope (reconfirmed in grasp_flow on a hard-key change).
            k,c=fit['fit']['k'],fit['fit']['c_mm'];source='learned' if fit.get('context_key')==key else 'reconfirm'
    except (OSError,ValueError,KeyError,TypeError):pass
    # A fixed 30mm cap cut wide objects (phone 74.4mm: formula 42.5mm -> 30mm,
    # flow-41bc1bd2). Scale the cap with half the width, bounded at 60mm.
    cap=min(60.,max(float(settings.get('preoffset_max_mm',30)),width/2+15))
    magnitude=float(np.clip(k*width+c,0,cap))
    return {'width_mm':float(width),'k':k,'c_mm':c,'source':source,'cap_mm':cap,
            'signed_mm':0. if slope is None else float(np.sign(slope)*magnitude)}


def apply_offset(plan,direction,offset):
    direction=np.asarray(direction,float);direction[2]=0;direction/=np.linalg.norm(direction)
    delta=direction*offset['signed_mm']
    for key in ['approach_xyz_mm','grasp_xyz_mm','verification_lift_xyz_mm']:
        plan[key]=(np.asarray(plan[key])+delta).tolist()
    plan['preoffset']=dict(offset,direction=direction.tolist(),delta_mm=delta.tolist())


def learn_offset(width,total_command,slope,key,trial,*,path=None,opening_percent=None,aperture_revision=None):
    if slope is None or width<=0:return
    path=path or DATA/'grasp_offset_learning.json'
    try:data=json.loads(path.read_text(encoding='utf8'))
    except (OSError,ValueError):data={}
    # Never wipe accumulated samples on a context change; adopt the new key.
    data.setdefault('samples',[])
    if data.get('context_key')!=key:data['previous_context_key']=data.get('context_key');data['context_key']=key
    samples=[s for s in data['samples'] if s['trial']!=trial]
    needed=float(total_command*np.sign(slope))
    if not 0<=needed<=50:return
    samples.append(dict(width_mm=float(width),offset_mm=needed,trial=trial,time=time.time(),opening_percent=opening_percent,aperture_revision=aperture_revision))
    data['samples']=samples[-40:]
    widths=np.array([s['width_mm'] for s in samples]);offsets=np.array([s['offset_mm'] for s in samples])
    # Do not fit two coefficients to repeated measurements of one width.
    if len(samples)>=4 and np.ptp(widths)>=10:
        x=np.c_[widths,np.ones(len(widths))];coef=np.linalg.lstsq(x,offsets,rcond=None)[0]
        residual=np.abs(x@coef-offsets);keep=residual<=max(3,float(np.median(residual)*2.5))
        if keep.sum()>=4 and np.ptp(widths[keep])>=10:
            coef=np.linalg.lstsq(x[keep],offsets[keep],rcond=None)[0]
            if 0<=coef[0]<=1.2 and -10<=coef[1]<=15:
                data['fit']={'k':float(coef[0]),'c_mm':float(coef[1]),'samples':int(keep.sum())}
    write(path,data)
