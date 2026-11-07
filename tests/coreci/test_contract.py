import copy
import json
from pathlib import Path
import tempfile
from support import build_inputs, entry, environment, registry_data, rejects
from coreci import common


def main():
    with environment(build_inputs()):
        assert common.inputs('build')['version'] == '1.2.3-alpha+test'
        with environment({'INPUT_BUILD_ID': 'wrong'}):
            rejects(common.inputs, 'build', text='build_id')
        with environment({'INPUT_REVISION': '0'}):
            rejects(common.inputs, 'build', text='revision')
    assert common.prerequisites('b=1.2.3-alpha-beta+meta-17') == {'b': ('1.2.3-alpha-beta+meta', 17)}
    for invalid in ['a=1.0.0-0', 'a=1.0.0-1,a=1.0.0-2', '../a=1.0.0-1']:
        rejects(common.prerequisites, invalid)
    rejects(common.document, b'{"x":1,"x":2}', text='duplicate')
    rejects(common.document, b'[]')
    rejects(common.document, b'{"unknown":NaN}')
    rejects(common.document, b'x'*(1024**2+1), text='1 MiB')
    assert common.workflow('Example/Recipes/.github/workflows/coreci-build.yml')[1].endswith('coreci-build.yml')
    rejects(common.workflow, 'Example/Recipes/coreci-build.yml')
    assert common.workflow_identity('example/RECIPES/.github/workflows/coreci-build.yml@refs/heads/test') == \
           common.workflow_identity('Example/Recipes/.github/workflows/coreci-build.yml')
    assert common.workflow_identity('Example/Recipes/.github/workflows/Coreci-build.yml') != \
           common.workflow_identity('Example/Recipes/.github/workflows/coreci-build.yml')
    rejects(common.https, 'https://name:password@example.test/')
    assert common.select({'matrix': [entry()]}, 't1') == entry()
    rejects(common.select, {'matrix': [entry(), entry()]}, 't1')
    rejects(common.select, {'matrix': [entry()]}, 'missing')
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary)/'registry.json'
        data = registry_data()
        path.write_text(json.dumps(data))
        assert common.registry(path) == data
        for presentation in (False, True):
            changed = copy.deepcopy(data)
            if presentation:
                changed['feeds']['test']['presentation'] = 'Example/Recipes/.github/workflows/coreci-status.yml'
                changed['status_url'] = 'https://controller.example/api/v1/status.json'
            for badges in (False, True):
                candidate = copy.deepcopy(changed)
                if not badges:
                    candidate.pop('badges')
                path.write_text(json.dumps(candidate))
                assert common.registry(path) == candidate
            changed['badges'] = 'http://unsafe/'
            path.write_text(json.dumps(changed))
            rejects(common.registry, path, text='HTTPS')
        changed = copy.deepcopy(data)
        changed.pop('badges')
        changed['feeds']['test']['presentation'] = 'Example/Recipes/.github/workflows/coreci-status.yml'
        path.write_text(json.dumps(changed))
        rejects(common.registry, path, text='status_url')
        changed['status_url'] = 'http://unsafe/'
        path.write_text(json.dumps(changed))
        rejects(common.registry, path, text='HTTPS')
        for mutate in [lambda d: d['feeds']['test'].update(url='http://unsafe/'),
                       lambda d: d['feeds']['test']['keys']['gpg'].update(file='../key'),
                       lambda d: d.update(default_feed='missing')]:
            changed = copy.deepcopy(data)
            mutate(changed)
            path.write_text(json.dumps(changed))
            rejects(common.registry, path)
    print('contract: input, registry, target, version and path boundaries passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
