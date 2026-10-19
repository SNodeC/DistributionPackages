"""Validate thin source entry points and central reusable workflow boundaries locally."""
from pathlib import Path
import sys
import yaml


def check(path):
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert workflow['on']['push']['tags'] == ['v[0-9]*.[0-9]*.[0-9]*']
    assert workflow['on']['workflow_dispatch']['inputs']['request']['required'] == 'true'
    assert 'fromJSON(inputs.request).intent' in workflow['run-name']
    assert set(workflow['jobs']) == {'notify', 'build'}
    for job, shared in [('notify', 'notify-release'), ('build', 'build-packages')]:
        entry = workflow['jobs'][job]
        assert entry['uses'] == f'SNodeC/DistributionPackages/.github/workflows/{shared}.yml@main'
        assert set(entry) == {'if', 'uses', 'secrets'}
        secret = 'PACKAGE_NOTIFY_APP_PRIVATE_KEY' if job == 'notify' else 'PACKAGE_CAPTURE_APP_PRIVATE_KEY'
        assert entry['secrets'] == {secret: '${{ secrets.' + secret + ' }}'}
    assert workflow['jobs']['notify']['if'] == "github.event_name == 'push' && github.event.deleted == false"
    assert workflow['jobs']['build']['if'] == "github.event_name == 'workflow_dispatch'"
    print(f'{path}: thin tag notification and coordinator build entry points passed')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Provide source build-distribution-packages.yml paths')
    for argument in sys.argv[1:]:
        check(Path(argument))
