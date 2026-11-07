"""Exercise the real sparse writer and commit machinery with missing package blobs."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from support import replace, environment
from golden import DATA, git_tree
from coreci import presentation as p


def git(root,*args,input=None):
    return subprocess.check_output(['git','-C',str(root),*args],input=input).decode().strip()


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
        base=git(root,'-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit-tree',
                 '5b55385c73aeeb18f4390f83db9ce834997c825e','-m','baseline')
        git(root,'update-ref','HEAD',base)
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
        env=dict(INPUT_FEED='packages',INPUT_GENERATION='1',GH_TOKEN='unit-test-only',
            GITHUB_WORKFLOW_REF='SNodeC/DistributionPackages/.github/workflows/coreci-status.yml@refs/heads/main')
        with environment(env),replace(sys,'argv',['presentation','run','--root',str(root)]), \
             replace(p,'registry',lambda:settings),replace(p,'status_fetch',lambda _:status), \
             replace(p,'metadata',lambda _:dict(id=1,default_branch='main')),replace(p,'declaration',lambda repo:definitions[repo]), \
             replace(p,'api',api),replace(p,'checked_push',push):
            p.main()
            first=git(root,'rev-parse','HEAD')
            p.main()
            assert git(root,'rev-parse','HEAD')==first and len(pushes)==1,'unchanged generation must not commit/push'
        after=set(git(root,'ls-tree','-r','--name-only','HEAD').splitlines())
        packages={name for name in names if name.endswith(('.deb','.rpm','.ipk','.apk'))}
        assert packages and packages<=after
        changed=set(git(root,'diff-tree','--no-commit-id','--name-only','-r',base,first).splitlines())
        assert changed and all(name in ('status.json','index.html','coreci/presentation.json') or name.startswith('status/') for name in changed)
        for name in packages:
            assert git(root,'rev-parse',base+':'+name)==git(root,'rev-parse',first+':'+name)
            assert not (root/name).exists(),'writer must not materialize package files'
        sample=next(iter(packages))
        oid=git(root,'rev-parse',first+':'+sample)
        probe=subprocess.run(['git','-C',str(root),'cat-file','-e',oid],capture_output=True)
        assert probe.returncode!=0,'package blobs must remain absent after committing'
    print('presentation writer: actual Git-tree rendering/commit, package identities preserved without blobs, no signing and no-op replay passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
