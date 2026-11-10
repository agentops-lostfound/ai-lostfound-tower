"""Update only the arrival margin of a matching, idle Studio installation.

Run with WSL python3. Default is read-only; --apply backs up and atomically
replaces one module. It never stops/restarts Studio or connects a robot.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from robot.studio_extension import install

MODULE = "runtime/saved_pose.py"
COMMENTS = ("# Residual motor error is expected even when re-requesting the current pose.\n"
            "# This is per arm joint in normalized units, independent of the tracking limit.\n")


def compatible_source(current, target):
    """Accept only the exact current release or its known 1.5/3 margin versions."""
    current, target = current.replace('\r\n', '\n'), target.replace('\r\n', '\n')
    if target.count('ARM_ARRIVAL_TOLERANCE = 5.0\n') != 1:
        raise ValueError('Expected arrival margin 5 release')
    without_comments = target.replace(COMMENTS, '')
    previous_three = without_comments.replace('ARM_ARRIVAL_TOLERANCE = 5.0\n',
                                               'ARM_ARRIVAL_TOLERANCE = 3.0\n')
    previous_original = without_comments.replace('ARM_ARRIVAL_TOLERANCE = 5.0\n', '').replace(
        '<= ARM_ARRIVAL_TOLERANCE', '<= 1.5')
    return current in (target, previous_three, previous_original)


def check_sources(bundle, manifest, installed):
    target = (bundle / 'backend' / MODULE).read_text(encoding='utf-8')
    if not compatible_source(installed['source'], target):
        raise RuntimeError('Installed saved_pose.py differs beyond the known arrival margin')
    for name in manifest['backend_files']:
        if name != MODULE and installed['hashes'].get(name) != manifest['files']['backend/' + name]:
            raise RuntimeError('Installed backend or poses differ: ' + name)


def update(bundle, apply=False):
    bundle = bundle.resolve()
    manifest = install.preflight(bundle)
    if install.sessions():
        raise RuntimeError('End Studio robot runtime sessions before updating')
    paths = json.dumps(manifest['backend_files'])
    probe = ("import hashlib,json; from pathlib import Path; "
             f"root=Path({install.BACKEND!r}); names={paths}; "
             f"print(json.dumps(dict(source=(root/{MODULE!r}).read_text(),"
             "hashes={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in names})))")
    installed = json.loads(install.docker('exec', install.CONTAINER,
        '/app/application/backend/.venv/bin/python', '-c', probe).stdout)
    check_sources(bundle, manifest, installed)
    if not apply:
        print('Compatible arrival update. Use --apply with no robot runtime sessions.')
        return
    if install.sessions():
        raise RuntimeError('A robot runtime session appeared; update cancelled')
    backup = Path(tempfile.mkdtemp(prefix='backup-arrival5-', dir=bundle.parent))
    target = install.BACKEND + '/' + MODULE
    install.docker('cp', install.CONTAINER + ':' + target, str(backup / 'saved_pose.py'))
    expected = installed['hashes'][MODULE]
    if hashlib.sha256((backup / 'saved_pose.py').read_bytes()).hexdigest() != expected:
        raise RuntimeError('Installed source changed during backup; update cancelled')
    new_file = bundle / 'backend' / MODULE
    pending = '/tmp/lf-arrival5-' + backup.name + '.py'
    install.docker('cp', str(new_file), install.CONTAINER + ':' + pending)
    # Recheck the old hash in the same process that performs atomic replacement.
    replace = ("import hashlib,os; from pathlib import Path; "
               f"p=Path({target!r}); "
               f"assert hashlib.sha256(p.read_bytes()).hexdigest()=={expected!r}, 'Source changed'; "
               f"os.replace({pending!r},str(p))")
    install.docker('exec', '-u', 'root', install.CONTAINER,
                   '/app/application/backend/.venv/bin/python', '-c', replace)
    actual = install.docker('exec', install.CONTAINER, 'sha256sum', target).stdout.split()[0]
    if actual != hashlib.sha256(new_file.read_bytes()).hexdigest():
        raise RuntimeError('Installed hash mismatch; preserve backup and inspect before reconnecting')
    print('Backup:', backup)
    print('Arrival margin 5 installed. Reconnect using Studio when ready; no connection was requested.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    update(args.bundle, args.apply)
