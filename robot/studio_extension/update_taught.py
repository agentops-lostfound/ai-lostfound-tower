"""Upgrade a known saved-pose installation using the shared taught bundle.

Run in WSL with Studio runtime sessions ended. Default is read-only. --apply
uses the existing complete backup/restore installer and restarts the container;
it never creates a robot session or sends movement commands.
"""
import argparse
import json
from pathlib import Path

from robot.studio_extension import install


def check_installed(manifest, installed):
    names = manifest['backend_files']
    target = {name: manifest['files']['backend/' + name] for name in names}
    accepted = [target, *manifest.get('previous_backend_sets', [])]
    if not any(installed == hashes for hashes in accepted):
        raise RuntimeError('Unknown installed backend/poses; preserve local teaching and compare sources')
    return target


def check_local_files(bundle):
    """Do not install teaching/settings different from the runner's checkout."""
    repo = Path(__file__).resolve().parents[2]
    for name in ('phone_carry.json', 'pick_sequences.json'):
        shared = json.loads((bundle / 'carry' / name).read_text())
        local = json.loads((repo / 'robot/config' / name).read_text(encoding='utf-8-sig'))
        if shared != local:
            raise RuntimeError('Bundle and checkout settings differ: ' + name)
    local_poses = json.loads((repo / 'outputs/robot_panel_live/poses.json').read_text(encoding='utf-8-sig'))
    shared = json.loads((bundle / 'backend/runtime/saved_poses.json').read_text())
    derived = set(shared.get('motion_profiles', {}))
    originals = {name: values for name, values in shared['poses'].items() if name not in derived}
    if originals != local_poses:
        raise RuntimeError('Bundle and checkout teaching differ; preserve local poses before upgrading')


def update(bundle, apply=False):
    bundle = bundle.resolve()
    manifest = install.preflight(bundle, mutate=apply)
    if install.sessions():
        raise RuntimeError('End Studio robot runtime sessions before updating')
    check_local_files(bundle)
    paths = json.dumps(manifest['backend_files'])
    probe = ("import hashlib,json;from pathlib import Path;"
             f"root=Path({install.BACKEND!r});names={paths};"
             "print(json.dumps({n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in names}))")
    installed = json.loads(install.docker('exec', install.CONTAINER,
        '/app/application/backend/.venv/bin/python', '-c', probe).stdout)
    target = check_installed(manifest, installed)
    if installed == target:
        print('Taught bundle already installed; no write/restart requested.')
        return
    if not apply:
        print('Known installation verified. --apply backs up backend/UI and restarts idle Studio; no robot connection.')
        return
    if install.sessions():
        raise RuntimeError('A robot runtime session appeared; update cancelled')
    # backup_and_apply rechecks these exact hashes before any write and keeps
    # the existing full rollback flow. Never accept arbitrary current hashes.
    install.backup_and_apply(bundle, {**manifest, 'original_backend': installed})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    update(args.bundle, args.apply)
