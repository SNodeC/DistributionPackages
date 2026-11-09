from contextlib import contextmanager, ExitStack
from pathlib import Path
from types import SimpleNamespace
import tempfile
from support import environment, registry_data, entry, replace, rejects
from coreci import publish
from contract import file_hash, write_json


def main():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        feed=root/'feed'
        artifacts=root/'packages'
        feed.mkdir()
        artifacts.mkdir()
        (feed/'README.md').write_bytes(b'Unrelated README\r\n')
        (feed/'unrelated').write_bytes(b'preserve these bytes')
        (artifacts/'a.deb').write_bytes(b'unsigned input')
        manifest=dict(build_id='a~t1~1.0.0~r1',package='a',version='1.0.0',revision=1,
                      target='t1',feed='test',entry=entry(),files={'a.deb':file_hash(artifacts/'a.deb')})
        write_json(artifacts/'manifest.json',manifest)
        env=dict(INPUT_BUILD_ID=manifest['build_id'],INPUT_PACKAGE='a',INPUT_VERSION='1.0.0',INPUT_REVISION='1',
                 INPUT_TARGET='t1',INPUT_CALLBACK_URL='',INPUT_BUILD_REPO='Example/Recipes',INPUT_BUILD_RUN_ID='1',
                 INPUT_ARTIFACT='coreci-'+manifest['build_id'],GITHUB_REPOSITORY='Example/Recipes',
                 GITHUB_WORKFLOW_REF='Example/Recipes/.github/workflows/coreci-publish.yml@refs/heads/test',
                 RUNNER_TEMP=str(root),GITHUB_OUTPUT=str(root/'outputs'),GH_TOKEN='unit-test-only',
                 GITHUB_STEP_SUMMARY=str(root/'summary'))
        events=[]
        def output(args):
            result='a'*40
            if 'get-url' in args:
                result='https://github.com/Example/Feed'
            return result
        def key(feed,kind,path):
            result=path/'test.asc'
            result.write_text('public test key')
            return result
        @contextmanager
        def private(work):
            path=Path(work)/'private'
            path.write_text('must not be mounted')
            try:
                yield {'APT_SIGNING_KEY':path}
            finally:
                path.unlink()
        @contextmanager
        def signer(*args):
            events.append('signing-boundary')
            yield root,[],root/'trusted.gpg'
        def indices(root,*args):
            path=root/'debian/dists/stable/main/binary-amd64/Packages'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'new index')
            return [path]
        def validate(root,entry,files,key,sdk):
            events.append('validate')
            assert key.parent.name=='public'
            assert not (key.parent/'private').exists()
            assert (root/files[0]).read_bytes()==b'unsigned input'
        def commit(root,changes,**kwargs):
            events.append('commit')
            assert kwargs['orphan'] is True
            assert 'unrelated' not in changes
            assert (root/'README.md').read_bytes().startswith(b'Unrelated README\r\n')
            return 'a'*40
        def push(*args):
            events.append('push')
            assert args[-2]=='unit-test-only'
            assert args[-1]=='a'*40
            return 'b'*40
        def availability(*args):
            events.append('availability')
        from coreci import validate as validator
        import contract
        with environment(env), ExitStack() as stack:
            for context in [replace(publish,'registry',registry_data),
             replace(publish,'metadata',lambda _:dict(default_branch='main')), replace(publish,'output',output),
             replace(publish,'public_key',key), replace(publish,'secrets',private), replace(publish,'signing_key',signer),
             replace(publish,'apt_indexes',indices),replace(publish,'prepare_commit',commit),replace(publish,'checked_push',push),
             replace(publish,'availability',availability), replace(validator,'validate',validate),
             replace(publish,'declaration',lambda _:dict(package='a',matrix=[entry()])),
             replace(contract,'package_metadata',lambda *args:dict(name='a',version='1.0.0-1~stable',arch='amd64'))]:
                stack.enter_context(context)
            publish.publish(artifacts,feed)
            assert events==['signing-boundary','validate','commit','push','availability']
            assert (root/'outputs').read_text()=='feed_commit='+'b'*40+'\n'
            events.clear()
            publish.publish(artifacts,feed)
            assert events==[], 'identical replay must not sign, validate, commit or push'
            (artifacts/'a.deb').write_bytes(b'conflicting unsigned bytes')
            manifest['files']['a.deb']=file_hash(artifacts/'a.deb')
            write_json(artifacts/'manifest.json',manifest)
            rejects(publish.publish,artifacts,feed,text='immutable')
            assert events==[], 'conflict must fail before signing'
            from coreci import presentation
            settings=registry_data()
            settings['feeds']['test']['presentation']='Example/Recipes/.github/workflows/coreci-status.yml'
            settings['status_url']='https://controller.example/api/v1/status.json'
            (artifacts/'a.deb').write_bytes(b'unsigned input')
            manifest['files']['a.deb']=file_hash(artifacts/'a.deb')
            write_json(artifacts/'manifest.json',manifest)
            for index,error in enumerate([ValueError('status output exceeds resource bound'),
                                           OSError('render write failed'),'receipt-link','receipt-root-link',None]):
                case= root / ('presentation-'+str(index))
                originals={'README.md':b'Unrelated README\r\n', 'index.html':b'old index',
                    'status.json':b'old status', 'status/controller.json':b'old controller',
                    'status/index.html':b'old status index', 'status/a.md':b'old page',
                    'status/assets/style.css':b'old asset', 'docs/a.md':b'old docs',
                    'install/a.md':b'old install', 'coreci/presentation.json':b'{"generation":1,"jobs":{}}'}
                for name,data in originals.items():
                    path=case/name
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(data)
                real_render = presentation.render
                if error == 'receipt-root-link':
                    outside = root / ('outside-'+str(index))
                    outside.mkdir()
                    (case/'receipts').symlink_to(outside, target_is_directory=True)
                if error == 'receipt-link':
                    existing = case/'receipts/aaa'
                    existing.mkdir(parents=True)
                    target = root/'existing-receipt.json'
                    target.write_text('{}')
                    (existing/'1.json').symlink_to(target)
                def receipt(root,*args):
                    relative='receipts/new/1.json'
                    path=root/relative
                    path.parent.mkdir(parents=True)
                    path.write_bytes(b'new receipt')
                    return relative
                def render(staged,exists=None):
                    if error == 'receipt-link':
                        real_render(staged, exists=exists)
                    assert staged!=case, 'optional renderer must not write into the publication checkout'
                    assert exists('debian/pool/stable/a_1.0.0-1~stable_amd64.deb')
                    assert (staged/'receipts/new/1.json').read_bytes()==b'new receipt'
                    assert (staged/'status/controller.json').read_bytes()!=originals['status/controller.json']
                    if error:
                        for name in originals:
                            path=staged/name
                            path.parent.mkdir(parents=True,exist_ok=True)
                            path.write_bytes(b'partially changed')
                        (staged/'status/new.html').write_bytes(b'must not leak')
                        raise error
                    (staged/'README.md').write_bytes(originals['README.md']+b'new data')
                    return ['README.md']
                events.clear()
                with replace(publish,'registry',lambda:settings),replace(presentation,'receipt',receipt), \
                     replace(presentation,'status_fetch',lambda _:dict(schema=1,generation=2)), \
                     replace(presentation,'metadata',lambda _:dict(id=1,default_branch='main')), \
                     replace(presentation,'declaration',lambda _:{}), \
                     replace(presentation,'project',lambda *args:dict(schema=1,executions=[])), \
                     replace(presentation,'render',render):
                    publish.publish(artifacts,case)
                assert events==['signing-boundary','validate','commit','push','availability']
                assert (case/'debian/pool/stable/a_1.0.0-1~stable_amd64.deb').read_bytes()==b'unsigned input'
                assert (case/'coreci/published/t1/a_1.0.0-1.sha256').read_text()==publish.ledger(manifest)
                assert (case/'receipts/new/1.json').read_bytes()==b'new receipt'
                if error:
                    assert all((case/name).read_bytes()==data for name,data in originals.items())
                    assert not (case/'status/new.html').exists()
                    message = 'status receipts cannot contain links' if isinstance(error, str) else str(error)
                    assert message in (root/'summary').read_text()
                else:
                    assert (case/'README.md').read_bytes()==originals['README.md']+b'new data'
                    assert (case/'coreci/presentation.json').read_text().find('"generation":2')>=0
                    assert all((case/name).read_bytes()==data for name,data in originals.items()
                               if name not in ('README.md','status/controller.json','coreci/presentation.json'))
        assert (feed/'unrelated').read_bytes()==b'preserve these bytes'
    print('publisher driver: validate-before-push, credential isolation, unchanged bytes, no-op and immutable conflict passed')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
