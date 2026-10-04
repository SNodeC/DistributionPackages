"""Stage tested per-target feeds; assemble the complete Linux publication."""
import importlib
import json
from pathlib import Path
import sys

from ci.repository import linux_matrix, unchanged

apt = importlib.import_module('ci.publish.apt')
rpm = importlib.import_module('ci.publish.rpm')


def stage(row, packages, bundle, output):
    if row not in linux_matrix():
        raise RuntimeError('Unknown Linux target')
    if row['distribution'] in {'debian', 'ubuntu'}:
        apt.stage(row['suite'], packages, bundle, output / 'linux', row['distribution'])
    else:
        rpm.stage(row, packages, bundle, output / 'linux')


def publish(incoming, checkout, bundle):
    unchanged(bundle)
    rows = linux_matrix()
    expected = {(r['distribution'], r['suite'], r['arch']) for r in rows}
    found = {p.relative_to(incoming / 'linux').parts for p in (incoming / 'linux').glob('*/*/*') if p.is_dir()}
    if not found or not found <= expected:
        raise RuntimeError(f'Unexpected Linux targets: {found - expected}')
    rows = [r for r in rows if (r['distribution'], r['suite'], r['arch']) in found]
    for distribution in ['debian', 'ubuntu']:
        if any(r['distribution'] == distribution for r in rows):
            apt.publish(incoming / 'linux', checkout, bundle, distribution)
    rpm_rows = [r for r in rows if r['distribution'] in {'rocky', 'fedora'}]
    rpm.publish(rpm_rows, incoming / 'linux', checkout, bundle)
    unchanged(bundle)


if __name__ == '__main__':
    command, *args = sys.argv[1:]
    if command == 'stage':
        stage(json.loads(args[0]), *(Path(p).resolve() for p in args[1:]))
    else:
        publish(*(Path(p).resolve() for p in args))
