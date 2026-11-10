import copy
import json
from pathlib import Path
import tempfile
from support import replace, registry_data, entry, rejects
from coreci import presentation as p


def main():
    settings=registry_data()
    settings['status_url']='https://controller.example/api/v1/status.json'
    settings['feeds']['test']['presentation']='Example/Recipes/.github/workflows/coreci-status.yml'
    doc=dict(package='a',title='A',depends_on=[],matrix=[entry()])
    status=dict(schema=1,generation=10,packages=[dict(name='a',sourceRepo=dict(owner='Example',repo='Source',branch='main'),
                released=dict(version='1.0.0',tag='v1.0.0'))],units=[])
    unit=dict(package='a',target='t1',feed='test',status='NoRelease',detail=None,position=None,
              inflight=None,published=None,failure=None,next=None)
    identity=dict(id='test',repository='Example/Feed',repository_id=1,branch='main')
    for kind,activity in [('NoRelease',None),('Settled','Published'),('Waiting','Waiting'),('Blocked','Waiting'),
            ('Ready','Pending'),('Dispatching','Pending'),('Building','Building'),('AwaitingPublish','Publishing'),
            ('Publishing','Publishing'),('Failed','Failed')]:
        u=copy.deepcopy(unit);u['status']=kind
        current=dict(version='1.0.0',revision=2,runId=99)
        if kind=='Settled':u['published']=dict(current,at=100,feedCommit='a'*40)
        elif kind=='Failed':u['failure']=dict(current,at=101,reason='failed');u['next']=dict(version='1.0.0',revision=3)
        elif kind in ('Dispatching','Building','AwaitingPublish','Publishing'):
            u['inflight']=dict(current,buildId='a~t1~1.0.0~r2',phase=kind,attempt=1)
        elif kind!='NoRelease':u['next']=dict(version='1.0.0',revision=2)
        facts=dict(status,units=[u])
        projected=p.project(facts,settings,{'Example/Source':doc},identity,{},lookup=lambda *args:'https://example.invalid/job')
        assert len(projected['executions'])==(0 if kind=='NoRelease' else 1)
        if activity:
            assert projected['executions'][0]['activity']==activity
    canonical=p.project(status,settings,{'example/source':doc},identity,{})
    assert canonical['projects'][0]['repository']=='Example/Source'
    stale=dict(unit,status='Waiting',next=dict(version='2.0.0',revision=3),
               failure=dict(version='1.0.0',revision=2,reason='old failure',runId=99,at=1))
    projected=p.project(dict(status,units=[stale]),settings,{'Example/Source':doc},identity,{},lookup=lambda *args:None)
    assert projected['executions'][0]['id']=='a~t1~2.0.0~r3'
    assert projected['executions'][0]['failure'] is None, 'a prior release failure must not label new waiting work'
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        (root/'status').mkdir()
        (root/'status/controller.json').write_text('previous bytes')
        (root/'coreci').mkdir()
        (root/'coreci/presentation.json').write_text(json.dumps(dict(generation=10,jobs={'99':'cached'})))
        assert p.refresh(root,settings,'test',status=status)==[]
        assert (root/'status/controller.json').read_text()=='previous bytes'
        assert p.refresh(root,settings,'test',status=dict(status,generation=9))==[]
        writes=[]
        def render(root,exists=None):
            writes.append(exists)
            (root/'status/README.md').write_text('rendered')
            return ['status/README.md']
        with replace(p,'metadata',lambda _:dict(id=1,default_branch='main')),replace(p,'declaration',lambda _:doc),replace(p,'render',render):
            paths=p.refresh(root,dict(settings,repositories=['Example/Source']),'test',exists=lambda _:True,status=dict(status,generation=11))
        assert paths==['status/controller.json','status/README.md','coreci/presentation.json']
        assert len(writes)==1 and callable(writes[0])
        assert json.loads((root/'coreci/presentation.json').read_text())==dict(generation=11,jobs={'99':'cached'})
    cache={}
    calls=[]
    def api(path,*args):
        calls.append(path)
        return dict(jobs=[dict(name='build',html_url='https://github.com/Example/Recipes/actions/runs/99/job/7')])
    with replace(p,'api',api):
        assert p.job(99,'Example/Recipes',cache)==p.job(99,'Example/Recipes',cache)
    assert len(calls)==1
    print('presentation: all activities, generation guard, callback-free projection and run-id job cache passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
