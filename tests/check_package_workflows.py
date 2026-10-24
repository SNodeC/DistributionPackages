"""Validate thin source entry points and central reusable workflow boundaries locally."""
from pathlib import Path
import sys
import yaml


def check(path):
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert workflow['on']['push']['tags'] == ['v[0-9]*.[0-9]*.[0-9]*']
    assert workflow['on']['workflow_dispatch']['inputs']['request'] == {'type': 'string', 'required': 'true'}
    assert set(workflow['jobs']) == {'notify', 'build'}
    for job, shared in [('notify', 'notify-release'), ('build', 'build-packages')]:
        entry = workflow['jobs'][job]
        assert entry['uses'] == f'SNodeC/DistributionPackages/.github/workflows/{shared}.yml@main'
        assert set(entry) == {'if', 'uses', 'secrets'}
        expected = ['PACKAGE_NOTIFY_APP_PRIVATE_KEY', 'PACKAGE_CAPTURE_APP_PRIVATE_KEY']
        assert entry['secrets'] == {key: '${{ secrets.' + key + ' }}' for key in expected}
    assert workflow['jobs']['notify']['if'] == "github.event_name == 'push' && github.event.deleted == false"
    assert workflow['jobs']['build']['if'] == "github.event_name == 'workflow_dispatch'"
    shared = yaml.load((Path(__file__).resolve().parents[1] / '.github/workflows/build-packages.yml').read_text(),
                       Loader=yaml.BaseLoader)
    tokens = {s['id']: s['with'] for j in shared['jobs'].values() for s in j.get('steps', [])
              if s.get('uses', '').startswith('actions/create-github-app-token@')}
    assert set(tokens) == {'capture', 'notify'}
    for name, permissions in [('capture', {'permission-actions': 'read', 'permission-contents': 'read'}),
                              ('notify', {'permission-actions': 'write'})]:
        assert tokens[name]['repositories'] == '${{ steps.location.outputs.name }}'
        assert {k: v for k, v in tokens[name].items() if k.startswith('permission-')} == permissions
    print(f'{path}: thin tag notification and coordinator build entry points passed')
    return None


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Provide source build-distribution-packages.yml paths')
    for argument in sys.argv[1:]:
        check(Path(argument))
