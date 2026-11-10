"""Exercise the real sparse writer and commit machinery with missing package blobs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from support import replace, environment
from golden import DATA, git_tree, remaining
from coreci import presentation as p


def git(root,*args,input=None):
    return subprocess.check_output(['git','-C',str(root),*args],input=input).decode().strip()



def bounded_promisor():
    with tempfile.TemporaryDirectory() as directory:
        work=Path(directory)
        remote=work/'origin.git'
        subprocess.run(['git','init','--bare','--quiet',str(remote)],check=True)
        payload=git(remote,'hash-object','-w','--stdin',input=os.urandom(3*1024**2))
        readme=git(remote,'hash-object','-w','--stdin',input=b'old presentation')
        tree=git(remote,'mktree',input=f'100644 blob {readme}\tREADME.md\n100644 blob {payload}\tpackage.deb\n'.encode())
        base=git(remote,'-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit-tree',tree,'-m','baseline')
        git(remote,'update-ref','refs/heads/main',base)
        git(remote,'symbolic-ref','HEAD','refs/heads/main')
        root=work/'feed'
        subprocess.run(['git','init','--quiet',str(root)],check=True)
        shutil.copytree(remote/'objects',root/'.git/objects',dirs_exist_ok=True)
        (root/'.git/objects'/payload[:2]/payload[2:]).unlink()
        git(root,'update-ref','HEAD',base)
        git(root,'remote','add','origin',str(remote))
        git(root,'config','remote.origin.promisor','true')
        settings=dict(feeds=dict(test=dict(repository='Example/Feed',presentation='Example/Recipes/.github/workflows/coreci-status.yml')))
        def refresh(root,*args):
            (root/'README.md').write_text('new presentation')
            (root/'coreci').mkdir(exist_ok=True)
            (root/'coreci/presentation.json').write_text('{"generation":1,"jobs":{}}')
            return ['README.md','coreci/presentation.json']
        pushes=[]
        def push(root,branch,token,expected):
            assert expected==base
            pushes.append(git(root,'rev-parse','HEAD'))
            return pushes[-1]
        env=dict(INPUT_FEED='test',GH_TOKEN='unit-test-only',GIT_TRACE=str(work/'trace'),
            GITHUB_WORKFLOW_REF='Example/Recipes/.github/workflows/coreci-status.yml@refs/heads/main')
        with environment(env),replace(sys,'argv',['presentation','run','--root',str(root)]), \
             replace(p,'registry',lambda:settings),replace(p,'metadata',lambda _:dict(default_branch='main')), \
             replace(p,'refresh',refresh),replace(p,'checked_push',push):
            p.main()
        assert len(pushes)==1 and (root/'README.md').read_text()=='new presentation'
        assert git(root,'rev-parse','HEAD:package.deb')==payload
        assert not (root/'.git/objects'/payload[:2]/payload[2:]).exists()
        assert not (root/'.git/objects/pack').exists() or not list((root/'.git/objects/pack').glob('*.pack'))
        assert ' fetch ' not in (work/'trace').read_text(), 'committing metadata must not fetch a blob exceeding the tool-output limit'
    return None


def main():
    with tempfile.TemporaryDirectory() as directory:
        work=Path(directory)
        tree=work/'tree.git'
        names=git_tree(tree)
        root=work/'feed'
        subprocess.run(['git','init','--quiet',str(root)],check=True)
        shutil.copytree(tree/'objects',root/'.git/objects',dirs_exist_ok=True)
        for folder in ('files','receipts'):
            for path in (DATA/folder).rglob('*'):
                if path.is_file():
                    git(root,'hash-object','-w','--stdin',input=path.read_bytes())
        git(root,'hash-object','-w','--stdin',input=(DATA/'pages.yml').read_bytes())
        base=git(root,'-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit-tree',
                 '5b55385c73aeeb18f4390f83db9ce834997c825e','-m','baseline')
        git(root,'update-ref','HEAD',base)
        git(root,'config','remote.origin.promisor','true')
        git(root,'config','remote.origin.url',str(work/'offline.git'))
        definitions=json.loads((DATA/'declarations.json').read_text())
        status=json.loads((DATA/'status.json').read_text())
        old=json.loads((DATA/'files/status/controller.json').read_text())
        urls={x['build_job_url'].split('/runs/')[1].split('/')[0]:x['build_job_url'] for x in old['executions'] if x['build_job_url']}
        settings=dict(default_feed='packages',build='SNodeC/DistributionPackages/.github/workflows/coreci-build.yml',
            repositories=list(definitions),status_url='https://controller.example/api/v1/status.json',
            feeds=dict(packages=dict(repository='Example/Feed',presentation='SNodeC/DistributionPackages/.github/workflows/coreci-status.yml')))
        pushes=[]
        def push(root,branch,token,expected):
            assert expected==base and token=='unit-test-only'
            pushes.append(git(root,'rev-parse','HEAD'))
            return pushes[-1]
        def api(path,*args):
            run=path.split('/runs/')[1].split('/')[0]
            return dict(jobs=[dict(name='build',html_url=urls[run])])
        env=dict(INPUT_FEED='packages',INPUT_GENERATION='1',GH_TOKEN='unit-test-only',GIT_TRACE=str(work/'git-trace'),
            GITHUB_WORKFLOW_REF='SNodeC/DistributionPackages/.github/workflows/coreci-status.yml@refs/heads/main')
        with environment(env),replace(sys,'argv',['presentation','run','--root',str(root)]), \
             replace(p,'registry',lambda:settings),replace(p,'status_fetch',lambda _:status), \
             replace(p,'metadata',lambda _:dict(id=1,default_branch='main')),replace(p,'declaration',lambda repo:definitions[repo]), \
             replace(p,'api',api),replace(p,'checked_push',push):
            p.main()
            first=git(root,'rev-parse','HEAD')
            p.main()
            assert git(root,'rev-parse','HEAD')==first and len(pushes)==1,'unchanged generation must not commit/push'
        assert ' fetch ' not in (work/'git-trace').read_text(), 'metadata-only writer must not fetch missing blobs'
        after=set(git(root,'ls-tree','-r','--name-only','HEAD').splitlines())
        packages={name for name in names if name.endswith(('.deb','.rpm','.ipk','.apk'))}
        assert packages and packages<=after
        changed=set(git(root,'diff-tree','--no-commit-id','--name-only','-r',base,first).splitlines())
        removed = {name for name in names if not remaining(name) or name=='.github/workflows/pages.yml'
                   or p.re.fullmatch(r'receipts/[0-9a-f]{64}/.+',name)}
        assert names-after==removed, (names-after)^removed
        assert not (root/'.github').exists()
        assert changed and all(name in removed or name=='coreci/presentation.json' or name.startswith('status/') for name in changed)
        for name in names-removed:
            if not name.startswith('status/') and name!='coreci/presentation.json':
                assert git(root,'rev-parse',base+':'+name)==git(root,'rev-parse',first+':'+name), name
        for name in packages:
            assert git(root,'rev-parse',base+':'+name)==git(root,'rev-parse',first+':'+name)
            assert not (root/name).exists(),'writer must not materialize package files'
        sample=next(iter(packages))
        oid=git(root,'rev-parse',first+':'+sample)
        probe=subprocess.run(['git','-C',str(root),'cat-file','-e',oid],capture_output=True,
                             env={**os.environ,'GIT_NO_LAZY_FETCH':'1'})
        assert probe.returncode!=0,'package blobs must remain absent after committing'
    bounded_promisor()
    print('presentation writer: actual Git-tree rendering/commit, package identities preserved without blobs, no signing and no-op replay passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
