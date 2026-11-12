"""Common tool opening-axis alignment fitted from ARM-camera observations at several positions."""
import hashlib,json
import numpy as np
from .config import DATA
from .approach_path import SIGN

def apply_alignment(reference):
    """Return reference with the fitted opening axis.

    The axis is only valid together with the wrist_roll SIGN it was fitted with,
    so a stale or mismatched profile is an error, not a silent fallback: the old
    [0,1,0] axis under the corrected SIGN would be ~90 deg off.
    Re-registering the fixed finger does not affect the wrist axis and is not checked.
    """
    path=DATA/'orientation_alignment.json'
    if not path.exists():raise ValueError('손목 벌림축 정합 파일(orientation_alignment.json)이 없습니다. 집기 계획을 중단합니다.')
    profile=json.loads(path.read_text(encoding='utf8'))
    if hashlib.sha256((DATA/'working_calibration.json').read_bytes()).hexdigest()!=profile['reference_sha256']:
        raise ValueError('working_calibration.json이 바뀌어 손목 벌림축 정합을 다시 맞춰야 합니다.')
    if profile.get('roll_sign')!=int(SIGN[4]):
        raise ValueError('손목 벌림축 정합의 wrist_roll 부호가 현재 코드와 다릅니다.')
    axis=np.asarray(profile['opening_axis_local'],float)
    if axis.shape!=(3,) or not np.isclose(np.linalg.norm(axis),1,atol=1e-6):raise ValueError('손목 벌림축 정합 값이 단위벡터가 아닙니다.')
    return dict(reference,opening_axis_local=axis.tolist(),orientation_alignment=profile)
