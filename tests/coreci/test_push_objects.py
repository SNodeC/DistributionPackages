"""Actual parentless pushes must not fetch or re-send an unchanged promisor blob."""
import contextlib
import io
import os
from pathlib import Path
import re
import subprocess
import tempfile
from support import environment, replace
from coreci import lease, presentation


def probe(shallow, root):
    remote=root/'origin.git'; local=root/'feed'
    def git(path,*args,**kwargs):
        result=subprocess.check_output(['git','-C',str(path),*args],**kwargs).decode().strip()
        return result
    subprocess.run(['git','init','--bare','--quiet',str(remote)],check=True)
    git(remote,'config','uploadpack.allowFilter','true')
    payload=git(remote,'hash-object','-w','--stdin',input=os.urandom(3*1024**2))
    readme=git(remote,'hash-object','-w','--stdin',input=b'old presentation')
    tree=git(remote,'mktree',input=f'100644 blob {readme}\tREADME.md\n100644 blob {payload}\tpackage.deb\n'.encode())
    base=git(remote,'-c','user.name=fixture','-c','user.email=test@example.invalid','commit-tree',tree,'-m','old')
    git(remote,'update-ref','refs/heads/main',base); git(remote,'symbolic-ref','HEAD','refs/heads/main')
    settings=dict(feeds=dict(test=dict(repository='Example/Feed',presentation='Example/Recipes/.github/workflows/coreci-status.yml')))
    run=subprocess.run
    progress=[]
    def command(args,**kwargs):
        actual=list(args)
        if actual[:2]==['git','clone']:
            assert '--depth=1' in actual and '--filter=blob:none' in actual
            actual[-2]=remote.as_uri()
            if not shallow:
                actual.remove('--depth=1')
        if 'push' in actual:
            result=run(actual,**dict(kwargs,stderr=subprocess.PIPE))
            progress.append(result.stderr)
        else:
            result=run(actual,**kwargs)
        return result
    def refresh(root,*args):
        (root/'README.md').write_text('new presentation')
        return ['README.md']
    capture=io.StringIO()
    env=dict(INPUT_FEED='test',GH_TOKEN='unit-test-only',
        GITHUB_WORKFLOW_REF='Example/Recipes/.github/workflows/coreci-status.yml@refs/heads/main')
    import sys
    with environment(env), replace(sys,'argv',['presentation','run','--root',str(local)]), \
         replace(presentation,'registry',lambda:settings),replace(presentation,'metadata',lambda _:dict(default_branch='main')), \
         replace(presentation,'refresh',refresh),replace(presentation.subprocess,'run',command),contextlib.redirect_stdout(capture):
        presentation.main()
    head=git(local,'rev-parse','HEAD')
    assert git(remote,'rev-parse','refs/heads/main')==head
    assert git(local,'rev-list','--parents','-n1','HEAD')==head, 'the feed commit must stay parentless'
    assert git(local,'rev-parse','HEAD:package.deb')==payload
    pack_bytes=sum(path.stat().st_size for path in (local/'.git/objects/pack').glob('*.pack'))
    writing=next(line for line in progress[0].splitlines() if 'Writing objects: 100%' in line and 'done.' in line)
    if shallow:
        assert 'push objects 3' in capture.getvalue()
        assert pack_bytes<2048, 'the unchanged package must never be downloaded'
        assert 'MiB' not in writing and '(3/3)' in writing, writing
    else:
        assert pack_bytes>3*1024**2 and 'MiB' in writing, 'the regression fixture must reproduce the old full-pack push'
    print(('fixed' if shallow else 'old'),writing,'local pack bytes',pack_bytes)
    return None


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        for shallow in (False,True):
            path=root/str(shallow); path.mkdir()
            probe(shallow,path)
    print('presentation push: old full-transfer reproduced; shallow blobless root push sends only 3 changed objects without fetching package bytes')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
