"""Offline golden acceptance over the public f1271dd presentation snapshot."""
import copy
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from support import ROOT, replace, environment, rejects
from coreci import presentation as p
from contract import canonical

DATA = Path(__file__).parent/'data/presentation'
TREE = '5b55385c73aeeb18f4390f83db9ce834997c825e'


def prepare(root):
    shutil.copytree(DATA/'files',root,dirs_exist_ok=True)
    shutil.copytree(DATA/'receipts',root/'receipts',dirs_exist_ok=True)
    for receipt in (root/'receipts').glob('*/*.json'):
        value=json.loads(receipt.read_text())
        names=[item['path'] for item in value['packages']]
        if value.get('development_export'):
            names.append(value['development_export']['path'])
        for name in names:
            path=root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.touch()
    return root


def git_tree(directory):
    subprocess.run(['git','init','--bare','--quiet',str(directory)],check=True)
    entries=json.loads((DATA/'production-tree.json').read_text())['tree']
    directories={''}|{e['path'] for e in entries if e['type']=='tree'}
    actual=None
    for folder in sorted(directories,key=lambda x:x.count('/'),reverse=True):
        prefix=folder+'/' if folder else ''
        children=[e for e in entries if e['path'].startswith(prefix) and '/' not in e['path'][len(prefix):]]
        raw=''.join(e['mode']+' '+e['type']+' '+e['sha']+'\t'+e['path'][len(prefix):]+'\n' for e in children)
        tree=subprocess.check_output(['git','--git-dir='+str(directory),'mktree','--missing'],input=raw.encode()).decode().strip()
        if not folder:
            actual=tree
    assert actual==TREE, 'fixture Git tree differs from the baseline commit'
    names=subprocess.check_output(['git','--git-dir='+str(directory),'ls-tree','-rz','--name-only',TREE]).decode().split('\0')
    return set(names)-{''}


def g1(mode, work):
    root=prepare(work/'feed')
    exists=None
    if mode=='tree':
        files=git_tree(work/'tree.git')
        for receipt in (root/'receipts').glob('*/*.json'):
            data=json.loads(receipt.read_text())
            names=[x['path'] for x in data['packages']]
            if data.get('development_export'):
                names.append(data['development_export']['path'])
            for name in names:
                (root/name).unlink(missing_ok=True)
        exists=lambda name:name in files
    p.render(root,ROOT/'status-templates',exists)
    rows=json.loads((DATA/'manifest.json').read_text())['files']
    for row in rows:
        assert hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
    print(f'G1 {mode}: {len(rows)}/122 baseline files byte-identical')


def g2(work):
    root=prepare(work/'feed')
    mapping=json.loads((DATA/'identifier-map.json').read_text())
    positions=[]
    def replaced(raw,path):
        text=raw.decode()
        chunks=[]
        start=0
        for match in re.finditer('|'.join(re.escape(old) for old in mapping),text):
            at=match.start();old=match.group();new=mapping[old]
            chunks.append(text[start:at])
            if text[max(0,at-9):at]=='receipts/':
                chunks.append(old)
            else:
                positions.append(dict(file=path,line=text.count('\n',0,at)+1,column=at-text.rfind('\n',0,at),before=old,after=new))
                chunks.append(new)
            start=match.end()
        chunks.append(text[start:])
        text=''.join(chunks)
        return text.encode()
    expected={row['path']:replaced((DATA/'files'/row['path']).read_bytes(),row['path'])
              for row in json.loads((DATA/'manifest.json').read_text())['files']}
    for file in (root/'receipts').glob('*/*.json'):
        file.write_bytes(replaced(file.read_bytes(),str(file.relative_to(root))))
    old=json.loads((DATA/'files/status/controller.json').read_text())
    definitions=json.loads((DATA/'declarations.json').read_text())
    jobs={str(int(x['build_job_url'].split('/runs/')[1].split('/')[0])):x['build_job_url'] for x in old['executions'] if x['build_job_url']}
    settings=dict(default_feed='packages',build='SNodeC/DistributionPackages/.github/workflows/coreci-build.yml')
    identity=dict(id='packages',**old['feed'])
    status=json.loads((DATA/'status.json').read_text())
    controller=p.project(status,settings,definitions,identity,dict(jobs))
    (root/'status/controller.json').write_text(canonical(controller)+'\n')
    p.render(root,ROOT/'status-templates')
    exceptions=[]
    def compare(a,b,path,file):
        if isinstance(a,dict) and isinstance(b,dict):
            assert set(a)==set(b),(file,path,set(a)^set(b))
            for key in a:
                compare(a[key],b[key],path+'/'+key,file)
        elif isinstance(a,list) and isinstance(b,list):
            assert len(a)==len(b),(file,path,len(a),len(b))
            if path.endswith('/executions') and a and all(isinstance(x,dict) and 'id' in x for x in a+b):
                assert {x['id'] for x in a}=={x['id'] for x in b},(file,path)
                old_positions={x['id']:i for i,x in enumerate(a)}
                for i,row in enumerate(b):
                    if old_positions[row['id']]!=i:
                        exceptions.append(dict(file=file,position=path+'/'+str(i),before_index=old_positions[row['id']],after_index=i,
                            id=row['id'],reason='New status unit order replaces old controller creation order; rendered cells are unchanged'))
                a=sorted(a,key=lambda x:x['id']);b=sorted(b,key=lambda x:x['id'])
            for i,(left,right) in enumerate(zip(a,b)):
                compare(left,right,path+'/'+str(i),file)
        else:
            assert a==b,(file,path,a,b)
    for name,raw in expected.items():
        actual=(root/name).read_bytes()
        if name.endswith('.json'):
            compare(json.loads(raw),json.loads(actual),'',name)
        else:
            assert actual==raw,name
    Path('G2-replaced-positions.json').write_text(json.dumps(positions,indent=2)+'\n')
    Path('G2-exceptions.json').write_text(json.dumps(exceptions,indent=2)+'\n')
    print(f'G2: all 122 files compared; {len(positions)} identifier replacements, {len(exceptions)} ordering exceptions; every other value and page byte matches')


def g3(work):
    root=prepare(work/'feed')
    sample=json.loads(next((root/'receipts').glob('*/*.json')).read_text())
    source=dict(sample['source'],commit=sample['source_commit']);version=source['tag'].removeprefix('v');package=source['package']
    target=sample['target'];target_id=target['id'];revision=9999
    build_id=f'{package}~{target_id}~{version}~r{revision}'
    # A new run lives in the recipe repository, while its publication belongs to the source repository.
    values=dict(build_repo='SNodeC/DistributionPackages',build_run_id='123')
    manifest=dict(source=source,package=package,version=version,revision=revision,target=target_id,
                  build_id=build_id,entry=target,files={})
    feed=dict(sample['feed'],url=sample['feed']['base_url'],environment='test')
    relative='test/new.deb';(root/'test').mkdir();(root/relative).write_bytes(b'unsigned fixture')
    info=dict(name=package+'-dev',version=version+'-9999',arch=target['arch'])
    build_job=dict(sample['build_job'],name='build',html_url='https://github.com/SNodeC/DistributionPackages/actions/runs/123/job/456')
    with environment(dict(GITHUB_REPOSITORY='SNodeC/DistributionPackages',GITHUB_RUN_ID='124')), \
         replace(p,'api',lambda *args:dict(jobs=[build_job])),replace(p,'package_metadata',lambda *args:info), \
         replace(p,'metadata',lambda *args:dict(default_branch='main')):
        receipt=p.receipt(root,manifest,values,feed,{'new.deb':relative})
    data=json.loads((root/receipt).read_text())
    assert data['source']['repository']==source['repository'] and data['build_result']['run']['html_url'].endswith('/123')
    # Rendering uses the new receipt's truthful source.repository, not the recipe run's repository.
    p.render(root,ROOT/'status-templates')
    rendered=json.loads((root/'status.json').read_text())
    row=next(row for row in rendered['publications'] if row['execution']==build_id)
    assert row['repository']==source['repository'] and row['revision']==9999 and row['version']==info['version']
    assert row['build_url']=='https://github.com/SNodeC/DistributionPackages/actions/runs/123'
    baseline=json.loads((DATA/'files/status.json').read_text())
    old=next(row for row in baseline['publications'] if row['repository']==source['repository'])
    assert set(row)==set(old), 'new publication row must preserve the baseline renderer schema'
    assert all(x['repository']!='SNodeC/DistributionPackages' for x in rendered['projects'])
    project=next(x for x in rendered['projects'] if x['repository']==source['repository'])
    page=(root/project['status_path']).read_text()
    new_row=next(row for row in re.findall(r'<tr>.*?</tr>',page,re.S) if info['version'] in row)
    baseline_page=(DATA/'files'/project['status_path']).read_text()
    old_rows=[row for row in re.findall(r'<tr>.*?</tr>',baseline_page,re.S)
              if '<code>'+target['arch']+'</code>' in row and old['version'] in row]
    def shape(row):
        row=re.sub(r'(href|src)="[^"]*"',r'\1="DATA"',row)
        row=re.sub(r'>[^<]*<','><',row)
        return row
    assert any(shape(new_row)==shape(old_row) for old_row in old_rows), 'new receipt must preserve baseline published-cell markup'
    assert build_job['html_url'] in new_row and info['version'] in new_row
    first=(root/receipt).read_bytes()
    next_version='9.0.0'
    second=dict(manifest,version=next_version,build_id=f'{package}~{target_id}~{next_version}~r{revision}',
                source=dict(source,tag='v'+next_version))
    with environment(dict(GITHUB_REPOSITORY='SNodeC/DistributionPackages',GITHUB_RUN_ID='124')), \
         replace(p,'api',lambda *args:dict(jobs=[build_job])), \
         replace(p,'package_metadata',lambda *args:dict(info,version=next_version+'-9999')), \
         replace(p,'metadata',lambda *args:dict(default_branch='main')):
        other=p.receipt(root,second,values,feed,{'new.deb':relative})
    assert other!=receipt and (root/receipt).read_bytes()==first, 'the same revision in another version must not collide'
    print('G3: baseline published-cell markup, source grouping, truthful run/job links and per-version receipt identity passed')


def main():
    mode=sys.argv[1]
    with tempfile.TemporaryDirectory() as directory:
        work=Path(directory)
        if mode in ('files','tree'):
            g1(mode,work)
        elif mode=='projection':
            g2(work)
        else:
            g3(work)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
