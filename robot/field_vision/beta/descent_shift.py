"""Learned shrink of the fixed-finger image gap between approach and grasp height.

The ARM camera rides on the fixed finger. Descending ~37mm, the object edge moved
17px toward the finger in the image (flow-d536cb28: edge 210 -> 193px at the finger
rows, gap +15px at approach -> ~0 at grasp; perspective and/or descent drift). The
gap is therefore required at approach height with this extra margin, and the margin
is re-measured after every descent.
"""
import json,time
from .config import DATA

PATH=DATA/'descent_gap_shift.json'
DEFAULT_PX=17.


def load(path=None):
    try:return float(json.loads((path or PATH).read_text(encoding='utf-8'))['shift_px'])
    except (OSError,ValueError,KeyError,TypeError):return DEFAULT_PX


def update(approach_gap_px,grasp_gap_px,trial,path=None):
    """EMA of (approach gap - grasp gap); clamped to a plausible 0..40px."""
    path=path or PATH
    observed=float(approach_gap_px)-float(grasp_gap_px)
    try:data=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):data={'shift_px':DEFAULT_PX,'samples':[]}
    data['samples']=[s for s in data.get('samples',[]) if s.get('trial')!=trial][-19:]
    data['samples'].append({'trial':trial,'approach_gap_px':float(approach_gap_px),'grasp_gap_px':float(grasp_gap_px),'observed_px':observed,'time':time.time()})
    data['shift_px']=min(40.,max(0.,.5*float(data.get('shift_px',DEFAULT_PX))+.5*observed))
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return data['shift_px']
