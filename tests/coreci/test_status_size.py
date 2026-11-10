"""Bound the complete rendered output without withholding template history."""
import copy
import json
from pathlib import Path
import tempfile
from golden import DATA
from coreci.contract import canonical, write_json
from coreci import presentation as p


def document_contract():
    job = dict(id=1, run_id=2, run_attempt=1, html_url='job', started_at=None, completed_at=None,
               steps=['discard'], runner_name='discard')
    assert set(p.normalized_job(job)) == {'id','run_id','run_attempt','html_url','started_at','completed_at'}
    assert job['steps'] == ['discard'] and p.normalized_job(None) is None
    return None


def projected(releases, root):
    definitions=json.loads((DATA/'declarations.json').read_text())
    samples=json.loads((DATA/'projection-samples.json').read_text())['samples']
    version=str(releases)+'.0.0'
    status=dict(schema=1,generation=1,packages=[],units=[])
    settings=dict(default_feed='packages',build='SNodeC/DistributionPackages/.github/workflows/coreci-build.yml')
    identity=dict(id='packages',repository='SNodeC/Packages',repository_id=1,branch='main')
    package_rows=0
    for repository,doc in definitions.items():
        owner,repo=repository.split('/')
        status['packages'].append(dict(name=doc['package'],sourceRepo=dict(owner=owner,repo=repo,branch='main'),
                                       released=dict(version=version,tag='v'+version)))
        for entry in doc['matrix']:
            status['units'].append(dict(package=doc['package'],target=entry['id'],feed='packages',status='Settled',
                inflight=None,failure=None,next=None,published=dict(version=version,revision=123,
                    runId=9999999999,at=1794132000+releases*600,feedCommit='a'*40)))
            for release in range(1,releases+1):
                value=copy.deepcopy(samples[doc['package']+'/'+entry['build']['format']]['receipt'])
                v=str(release)+'.0.0'
                execution=doc['package']+'~'+entry['id']+'~'+v+'~r123'
                value.update(execution=execution,attempt=execution+':1',revision=123,target=entry,
                             published_utc=p.utc(1794132000+release*600),compatibility=p.coordinates(entry))
                value['source'].update(repository=repository,package=doc['package'],tag='v'+v)
                # Existing full Actions job responses must be normalized on read, without changing the receipt.
                value['build_job']['steps']=[{'name':'historical job metadata','text':'x'*4096}]
                for item in value['packages']:
                    item.update(path='projection/'+entry['id']+'/'+v+'/'+item['name'],version=v+'-123')
                if value.get('development_export'):
                    value['development_export']['path']='dev/'+entry['id']+'/'+v+'.tar.gz'
                (root/'receipts'/execution).mkdir(parents=True)
                write_json(root/'receipts'/execution/'123.json',value)
                package_rows+=len(value['packages'])
    assert len(status['units'])==178
    controller=p.project(status,settings,definitions,identity,{},lookup=lambda *args:None)
    (root/'status').mkdir()
    write_json(root/'status/controller.json',controller)
    paths=p.render(root,exists=lambda _:True)
    sizes={name:(root/name).stat().st_size for name in paths}
    assert len(controller['executions'])==178
    assert set(paths)=={'status/README.md','status/snodec.md','status/snodec-idp.md','status/mqttsuite.md'}
    assert not (root/'status.json').exists() and not (root/'index.html').exists()
    assert sum(sizes.values())<32*1024**2
    # The renderer must leave historical receipt inputs intact.
    assert all('steps' in json.loads(path.read_text())['build_job'] for path in (root/'receipts').glob('*/*.json'))
    print(canonical(dict(releases=releases,units=178,receiptRows=package_rows,
                         totalBytes=sum(sizes.values()))))
    return sum(sizes.values())


def main():
    document_contract()
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        sizes=[projected(count,root/str(count)) for count in (1,5,6)]
    assert sizes[1]<=sizes[0] and sizes[2]<=sizes[0], sizes
    print('178 units: all rendered output below 32 MiB, no growth after five further releases; history retained for templates')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
