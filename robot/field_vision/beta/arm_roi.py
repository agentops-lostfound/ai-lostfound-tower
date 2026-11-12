"""v0.2.69: limit the ARM-camera target outline to a detector box.

The colour/background masks that find the target in the wrist camera treat every
non-green pixel as a possible object, so the outline could jump to the white wall /
desk beyond the storage tray. During a grasp the same detector as the analysis view
(OWL on the ARM frame, ~0.7s) is run once; the target box is then tracked frame by
frame by the camera's LiveOverlay (shown on the ARM stream as TARGET) and every
outline measurement keeps only pixels inside that box plus a margin. Lost track ->
re-detect at the next ensure(); no box -> old unrestricted behaviour.
"""
import copy
import time

import numpy as np

MARGIN_PX, MARGIN_FRACTION = 25, .15
_active = {'camera': None, 'track': None}


def overlap_small(a, b):
    ix = max(0., min(a[2], b[2]) - max(a[0], b[0])); iy = max(0., min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2]-a[0])*(a[3]-a[1]), (b[2]-b[0])*(b[3]-b[1]))
    return ix*iy/max(small, 1.)


def choose_target(items, size, inner_x=None):
    """Group nested/overlapping boxes (a USB body and its cap part) and pick the group
    nearest the fixed finger's inner edge at mid height (target position after approach).
    Returns the index of the largest box in that group, or None."""
    w, h = size
    boxes = [(i, [float(v) for v in o['bbox']]) for i, o in enumerate(items)
             if (o['bbox'][2]-o['bbox'][0])*(o['bbox'][3]-o['bbox'][1]) < .92*w*h]   # v0.2.74: a close phone fills most of the frame
    groups = []
    for i, b in sorted(boxes, key=lambda x: -(x[1][2]-x[1][0])*(x[1][3]-x[1][1])):
        for g in groups:
            if any(overlap_small(b, o) > .5 for _, o in g): g.append((i, b)); break
        else: groups.append([(i, b)])
    if not groups: return None
    px = inner_x if inner_x is not None else w/2
    def distance(g):
        i, b = g[0]; cx, cy = (b[0]+b[2])/2, (b[1]+b[3])/2
        return abs(cx-px) + .5*abs(cy-h/2)
    return min(groups, key=distance)[0][0]


def expand(box, size):
    w, h = size; x1, y1, x2, y2 = box
    mx = max(MARGIN_PX, (x2-x1)*MARGIN_FRACTION); my = max(MARGIN_PX, (y2-y1)*MARGIN_FRACTION)
    return [max(0, int(x1-mx)), max(0, int(y1-my)), min(w, int(x2+mx)), min(h, int(y2+my))]


def current_box(size):
    """Expanded box of the tracked target in the latest ARM frame, or None."""
    camera = _active['camera']
    if camera is None: return None
    track_id = _active['track']
    for t in camera.overlay.visible():
        if t['id'] == track_id and t.get('target'): return expand(t['bbox'], size)
    return None


def apply(mask, size=None):
    """Zero mask pixels outside the tracked target box (no-op without a box)."""
    h, w = mask.shape[:2]
    box = current_box((w, h))
    if box is None: return mask
    keep = np.zeros_like(mask); x1, y1, x2, y2 = box
    keep[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
    return keep


def activate(camera): _active.update(camera=camera, track=None)


class paused:
    """Measure without the box (lift check: the tracked box can drift while lifting)."""
    def __enter__(self): self.saved = dict(_active); _active['camera'] = None
    def __exit__(self, *_): _active.update(self.saved)


def deactivate():
    camera = _active['camera']; _active.update(camera=None, track=None)
    if camera is not None:
        with camera.overlay.lock:
            for t in camera.overlay.tracks: t.pop('target', None)


def ensure(engine, cancel, target_id, inner_x=None, log=lambda *_: None, timeout=8):
    """Detect on the latest ARM frame unless the target box is still tracked."""
    camera = _active['camera']
    if camera is None: return None
    image, seq, captured = camera.snapshot()
    if current_box(image.size): return current_box(image.size)
    job = engine.submit('detect', image.copy(), source='arm', frame_id=seq, captured=captured, with_features=False)
    deadline = time.monotonic()+timeout
    while True:
        with engine.lock:
            live = next((j for j in engine.jobs if j['id'] == job['id']), None)
            job = copy.deepcopy(live) if live else job
        if job['status'] in ('complete', 'failed', 'cancelled'): break
        if cancel.is_set() or time.monotonic() > deadline:
            log({'arm_roi': 'detect_timeout'}); return None
        cancel.wait(.05)
    items = (job.get('result') or {}).get('items') or []
    index = choose_target(items, image.size, inner_x) if job['status'] == 'complete' else None
    if index is None:
        log({'arm_roi': 'no_box', 'frame_id': seq, 'boxes': len(items)}); return None
    camera.overlay.mark_target(seq, items[index]['index'], target_id)
    track = next((t for t in camera.overlay.tracks if t.get('target')), None)
    _active['track'] = track['id'] if track else None
    box = current_box(image.size)
    log({'arm_roi': 'detected', 'frame_id': seq, 'bbox': items[index]['bbox'], 'roi': box, 'boxes': len(items)})
    return box
