"""v0.2.76: large items — after the floor descent, bring the fixed finger close to the side.

flow-e1f0b648 (sky phone, 73mm): the boundary was right (30.7px = ~5mm at the floor),
the jaw closed, but the moving finger had to push the phone ~5mm across the board
to the fixed finger and the phone stayed on the board (lift: not held). User 11-12:
"하강 후 물체와 가깝게 붙는 움직임이 있으면 좋을것 같은데".

At the floor the camera is closer than at the approach height, so the learned px/mm
from the approach is an UNDER-estimate of px per mm here: px/slope over-estimates the
millimetres. Move only a fraction, re-measure, at most two steps, never past the edge.
"""
TARGET_PX = 6.       # ~1mm left between finger and side
START_ABOVE_PX = 12. # already this close -> no move
FRACTION = .7
MAX_STEPS = 2
LIFT_MM = 1.         # slide 1mm above the commanded floor height, then lower back


MIN_MOVE_MM = 1.0     # v0.2.80: a 0.7mm command did not move the gap at all (servo dead zone)


def measured_slope(gap_before, gap_after, mm):
    """px per mm actually seen at the floor from the previous snug step (signed like the
    learned slope: positive mm widens the gap). None if the step was too small to tell."""
    if gap_before is None or gap_after is None or abs(mm) < .8:return None
    slope = (gap_after - gap_before) / mm
    return slope if abs(slope) >= 1.5 else None


def step_mm(gap_px, slope_px_per_mm, used_mm, limit_mm, measured=False):
    """Signed lateral command (same sign convention as the descent correction:
    positive mm widens the gap). None = no move.
    measured=True: the slope comes from the previous step AT THE FLOOR (flow-fba8acfb:
    approach slope 6.4 px/mm, floor response 4.2 px/mm) -> move the full amount."""
    if gap_px is None or not slope_px_per_mm or gap_px <= START_ABOVE_PX:return None
    mm = (TARGET_PX - gap_px) / slope_px_per_mm * (1. if measured else FRACTION)
    if abs(mm) < MIN_MOVE_MM:mm = MIN_MOVE_MM if mm > 0 else -MIN_MOVE_MM
    room = limit_mm - abs(used_mm)
    if room <= .3:return None
    if abs(mm) > room:mm = -room if mm < 0 else room
    return float(mm) if abs(mm) >= .3 else None



def path_floor(start_z, plane_z):
    """Lowest allowed TCP height on the snug path: never below the board by more than
    1mm unless the finger is already there, and never lower than it already is (-0.5mm)."""
    return min(float(start_z), float(plane_z) - 1.) - .5
