"""Check source package-workflow boundaries locally without dispatches or tags."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml


def check(path):
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    inputs = workflow['on']['workflow_dispatch']['inputs']
    assert inputs['release_tag']['required'] == 'true'
    assert workflow['on']['push']['tags'] == ['v[0-9]*.[0-9]*.[0-9]*']
    assert workflow['on']['repository_dispatch']['types'] == ['build-dependent-packages']
    prepare = workflow['jobs']['prepare']
    assert "github.event_name == 'workflow_dispatch' && github.ref == format('refs/heads/{0}', github.event.repository.default_branch)" in prepare['if']
    steps = prepare['steps']
    download = next(s for s in steps if s.get('uses', '').startswith('actions/download-artifact@'))
    assert download['if'] == "github.event_name == 'repository_dispatch' || github.run_attempt > 1"
    initialize = next(s for s in steps if s.get('id') == 'initialize')
    assert initialize['if'] == "(github.event_name == 'push' || github.event_name == 'workflow_dispatch') && github.run_attempt == 1"
    assert initialize['env']['RELEASE_TAG'] == '${{ inputs.release_tag || github.ref_name }}'
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        status = root / 'feed/ci/publish/status.sh'
        status.parent.mkdir(parents=True)
        status.write_text('#!/bin/bash\nprintf "%s" "$RELEASE_TAG" > reserved\n')
        binary = root / 'bin'
        binary.mkdir()
        python = binary / 'python3'
        python.write_text('#!/bin/bash\n[[ "$*" == "-m ci.repository prepare published bundle" ]]\nprintf "%s" "$RELEASE_TAG" > captured\n')
        python.chmod(0o755)
        for tag in ('v2.0.0', 'v1.0.2', 'v12.34.56', 'master', 'Book-1.0', 'v01.0.0', 'v1.0', 'v1.0.0;touch injected'):
            for name in ('reserved', 'captured', 'injected'):
                (root / name).unlink(missing_ok=True)
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', initialize['run']],
                                    cwd=root, capture_output=True, text=True,
                                    env=os.environ | {'PATH': str(binary) + ':' + os.defpath,
                                                      'RELEASE_TAG': tag, 'GITHUB_REF': 'refs/heads/master'})
            valid = tag in ('v2.0.0', 'v1.0.2', 'v12.34.56')
            assert (result.returncode == 0) == valid, (path, tag, result.stderr)
            assert (root / 'captured').exists() == valid
            assert (root / 'reserved').exists() == valid
            assert not (root / 'injected').exists()
            if valid:
                assert (root / 'captured').read_text() == tag
    print(f'{path}: manual/tag/dependent routing and 8 tag-validation cases passed')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Provide source build-distribution-packages.yml paths')
    for argument in sys.argv[1:]:
        check(Path(argument))
