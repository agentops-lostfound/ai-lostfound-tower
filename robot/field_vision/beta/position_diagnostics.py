"""Separate numerical IK error, encoder following error, and physical observations."""
import numpy as np


def compare_positions(requested, commanded, measured, *, joint_errors=None):
    requested, commanded, measured = map(lambda p: np.asarray(p, float),
                                         (requested, commanded, measured))
    def error(vector):
        return {'delta_mm': vector.tolist(), 'xy_mm': float(np.linalg.norm(vector[:2])),
                'distance_mm': float(np.linalg.norm(vector))}
    return {'requested_mm': requested.tolist(), 'commanded_model_mm': commanded.tolist(),
            'feedback_model_mm': measured.tolist(),
            'ik_error': error(commanded-requested),
            'following_error': error(measured-commanded),
            'total_model_error': error(measured-requested),
            'joint_error_ticks': joint_errors,
            'physical_alignment': 'unmeasured',
            'note': '관절 피드백의 모델 FK 기준. 실제 TCP·보관함 정합·영상 높이 오차는 별도 실측 필요'}


def from_report(report):
    arrival = report.get('arrival_orientation')
    route = report.get('approach_route', {}).get('waypoints')
    if not arrival or not route:
        return None
    result = compare_positions(report['plan']['approach_xyz_mm'], route[-1]['xyz_mm'], arrival['xyz_mm'])
    result.update(trial_id=report['id'], captured=report.get('finished', report.get('started')))
    return result


def observed_translation(diagnostic, board_delta, frame):
    """Translation estimate at ONE pose, not a fitted TCP/base calibration."""
    delta = np.asarray(frame['x_axis'])*board_delta[0]+np.asarray(frame['y_axis'])*board_delta[1]
    # Physical correction d describes motion from the measured pose, whose FK
    # already differs from the original target by e. New model target = target+e+d.
    candidate = np.asarray(diagnostic['total_model_error']['delta_mm'])+delta
    candidate[2] = 0  # User supplied XY only; never infer a Z correction.
    return {'board_delta_mm': list(board_delta), 'observed_robot_motion_mm': delta.tolist(),
            'candidate_target_delta_mm': candidate.tolist(), 'applied': False,
            'scope': 'single_pose_observation',
            'note': '단일 자세 눈대중 관측. TCP 오프셋·베이스 오차의 구분/보정 확정 아님'}
