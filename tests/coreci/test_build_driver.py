import os
from pathlib import Path
import subprocess
import shlex
import tempfile
from support import build_inputs, entry, environment, registry_data, replace, rejects
from coreci import build
from coreci.contract import write_json, read_json


def probe(fmt):
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        source=root/'source'
        recipe=root/'recipe'
        source.mkdir()
        (source/'.git').mkdir()
        (source/'.git/token').write_text('must not enter build image')
        (source/'payload').write_text('source')
        (recipe/'ci').mkdir(parents=True)
        target=entry(fmt)
        openwrt=fmt in ('ipk','apk')
        if openwrt:
            target.update(family='openwrt',distribution='openwrt')
            target['build']=dict(format=fmt,target='x86/64',release='test')
        write_json(recipe/'ci/packages.json',dict(package='a',depends_on=[],matrix=[target],
                   build={target['family']:'ci/hook.sh'},build_dependencies={fmt:['cmake']}))
        calls=[]
        run = subprocess.run
        host=dict(image='example:stable',platform='linux/amd64',resolved_image='example@sha256:'+'0'*64)
        def prepare(target,environment,destination):
            sdk=destination/'extracted/test-sdk'
            template=sdk/'staging_dir/host/lib/meson/openwrt-cross.txt.in'
            template.parent.mkdir(parents=True)
            template.write_text('private host-generated SDK template')
            template.chmod(0o600)
            template.parent.chmod(0o700)
            (sdk/'template-link').symlink_to(template.relative_to(sdk))
            (destination/'sdk.archive').write_bytes(b'archive must not enter build image')
            (destination/'query.mk').write_text('preparation only')
            return sdk,Path('staging_dir/target')
        def command(args,**kwargs):
            calls.append(args)
            if args[:3] == ["chmod", "-R", "a+rX"]:
                run(args, **kwargs)
            if args[:2]==['docker','build']:
                context=Path(args[-1])
                assert not (context/'source/.git').exists()
                dockerfile=(context/'Dockerfile').read_text()
                assert 'cmake' in dockerfile and 'COPY prerequisites /inputs/prerequisites' in dockerfile
                sdk_copies=[shlex.split(line) for line in dockerfile.splitlines()
                            if line.startswith('COPY --chown=')]
                if openwrt:
                    assert not sdk_copies, 'the SDK must not enter an image layer'
                    template=context/'sdk/extracted/test-sdk/staging_dir/host/lib/meson/openwrt-cross.txt.in'
                    assert template.stat().st_mode & 0o444 == 0o444, 'uid 1000 must read host-generated SDK files'
                    assert template.parent.stat().st_mode & 0o111 == 0o111, 'uid 1000 must traverse SDK directories'
                    assert (context/'sdk/extracted/test-sdk/template-link').is_symlink()
                    ignored=(context/'.dockerignore').read_text().splitlines()
                    assert 'sdk' in ignored, 'SDK and archive must stay outside the Docker context'
                else:
                    assert not sdk_copies
            if args[:2]==['docker','run']:
                assert '--user=1000:1000' in args and '--read-only' in args and '--cap-drop=ALL' in args
                assert ('--cpus=2' if openwrt else '--cpus=4') in args
                assert '--env' not in args and '-e' not in args, 'no credentials forwarded to container'
                scratch = {args[i+1].split(':',1)[0]: args[i+1].split(':',1)[1]
                           for i, arg in enumerate(args) if arg == '--tmpfs'}
                for directory in ('/tmp', '/var/tmp'):
                    assert directory in scratch, 'compiler and RPM temporary directories must be writable'
                    assert 'rw' in scratch[directory] and 'mode=1777' in scratch[directory]
                sdk_mounts = [s for s in args if 'target=/sdk' in s]
                assert len(sdk_mounts) == int(openwrt)
                if openwrt:
                    assert sdk_mounts[0].endswith('target=/sdk,readonly')
                assert any('target=/source,readonly' in s for s in args)
                assert any('target=/definition,readonly' in s for s in args)
                assert any('target=/tool,readonly' in s for s in args)
                if '--inspect' in args:
                    assert '--network=none' in args
                    destination=root/'packages'
                    destination.mkdir(exist_ok=True)
                    write_json(destination/'manifest.json',dict(files={},package='a'))
                    (destination/'manifest.json').chmod(0o444)
            return subprocess.CompletedProcess(args,0)
        with environment(dict(build_inputs(),RUNNER_TEMP=str(root))), replace(build,'registry',registry_data), \
             replace(build,'native',lambda _:host), replace(build,'sdk',lambda *args:{}), \
             replace(build,'prepare',prepare), replace(build,'output',lambda _: 'a'*40), replace(build.subprocess,'run',command):
            build.build(source,recipe,root/'packages')
        assert read_json(root/'packages/manifest.json')['source'] == dict(repository='Example/Source',tag='v1.2.3-alpha+test',package='a',commit='a'*40)
        assert read_json(root/'packages/manifest.json')['prerequisites'] == {}
        assert os.access(root/'packages/manifest.json',os.W_OK), 'final manifest must be writable by its host producer'
        assert sorted(p.name for p in (root/'packages').iterdir()) == ['manifest.json']
        assert [c[0] for c in calls].count('chmod') == int(openwrt)
        docker_calls = [c for c in calls if c[0] == 'docker']
        assert [c[1] for c in docker_calls] == ['build','run','run','image']
        assert '--inspect' in docker_calls[2]
    return 0


def main():
    probe('deb')
    probe('rpm')
    probe('ipk')
    probe('apk')
    print('build driver: deb/rpm/ipk/apk isolation, SDK ownership, credential-free mounts and cleanup passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
