"""Fixed inverse servo offsets. Original teaching values are never rewritten."""
import json
from pathlib import Path

from robot.studio_extension.runtime.saved_pose import checked_command_correction, vector


def load_command_corrections(poses, path=None):
    path = Path(path) if path else Path(__file__).with_name('config') / 'pose_command_corrections.json'
    if not path.exists():
        return {}
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if config['schema'] != 'pose_command_corrections.v1':
        raise ValueError('Unknown command-correction schema')
    result = {}
    for name, profile in config['poses'].items():
        # Retaught or fixture poses must never inherit an older inverse offset.
        if name not in poses or profile['reference'] != poses[name]:
            continue
        checked_command_correction(profile, vector(poses[name]))
        result[name] = profile
    return result
