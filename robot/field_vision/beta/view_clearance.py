"""Conditional closed-jaw view acquisition; never required for small objects."""
import numpy as np


def needs_view(width_mm,slope,frame_width,fixed_edge_x=None,localization_ok=True):
    expected=None if slope is None else abs(slope)*width_mm
    large=width_mm>=60
    missing=not localization_ok or fixed_edge_x is None or not 8<fixed_edge_x<frame_width-8
    return {'needed':large and missing,'large':large,'expected_width_px':expected,
            'reason':'고정 손가락 쪽 경계 시야 부족' if large and missing else '현재 시야에서 고정 쪽 경계 사용'}


def view_heights(approach):
    return sorted(set(min(100.,float(approach)+d) for d in [20,35] if min(100.,float(approach)+d)>approach+5))


def validate_view_path(model,start,end,plane,minimum_z,max_tilt_deg=10):
    # v0.2.45 B7: tilt limit comes from grasp_flow's stage_tilt (10, or 18 at far cells).
    for t in np.linspace(0,1,101):
        f=model.forward(start+(end-start)*t,with_points=False)
        if f['position'][2]<max(plane+20,minimum_z-3) or -f['tool_axis'][2]<np.cos(np.radians(max_tilt_deg)):
            raise ValueError('시야 확보 경로의 높이/방향 조건 미충족')
