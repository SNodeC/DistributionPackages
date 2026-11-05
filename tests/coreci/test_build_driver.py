import os
from pathlib import Path
import subprocess
import tempfile
from support import build_inputs, entry, environment, registry_data, replace, rejects
from coreci import build
from contract import write_json


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        source=root/'source'
        recipe=root/'recipe'
        source.mkdir()
        (source/'.git').mkdir()
        (source/'.git/token').write_text('must not enter build image')
        (source/'payload').write_text('source')
        (recipe/'ci').mkdir(parents=True)
        write_json(recipe/'ci/packages.json',dict(package='a',depends_on=[],matrix=[entry()],
                   build=dict(native='ci/hook.sh'),build_dependencies={'deb':['cmake']}))
        calls=[]
        host=dict(image='example:stable',platform='linux/amd64',resolved_image='example@sha256:'+'0'*64)
        def command(args,**kwargs):
            calls.append(args)
            if args[:2]==['docker','build']:
                context=Path(args[-1])
                assert not (context/'source/.git').exists()
                dockerfile=(context/'Dockerfile').read_text()
                assert 'cmake' in dockerfile and 'COPY prerequisites /inputs/prerequisites' in dockerfile
            if args[:2]==['docker','run']:
                assert '--user=1000:1000' in args and '--read-only' in args and '--cap-drop=ALL' in args
                assert '--env' not in args and '-e' not in args, 'no credentials forwarded to container'
                assert any('target=/source,readonly' in s for s in args)
                assert any('target=/definition,readonly' in s for s in args)
                assert any('target=/core_ci,readonly' in s for s in args)
                if '--inspect' in args:
                    assert '--network=none' in args
            return subprocess.CompletedProcess(args,0)
        with environment(dict(build_inputs(),RUNNER_TEMP=str(root))), replace(build,'registry',registry_data), \
             replace(build,'native',lambda _:host), replace(build.subprocess,'run',command):
            build.build(source,recipe,root/'packages')
        assert [c[1] for c in calls]==['build','run','run','image']
        assert '--inspect' in calls[2]
    print('build driver: disposable image, credential-free mounts, separate inspection and cleanup passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
