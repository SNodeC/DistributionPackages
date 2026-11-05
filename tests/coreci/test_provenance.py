import copy
from support import environment, registry_data, replace, rejects
from coreci import publish


def main():
    values=dict(build_repo='Example/Recipes',build_run_id='42')
    good=dict(repository=dict(full_name='Example/Recipes'), path='.github/workflows/coreci-build.yml',
              event='workflow_dispatch',conclusion='success',head_branch='test-branch',status='completed')
    with environment({'GITHUB_REF_NAME':'test-branch'}):
        with replace(publish,'api',lambda *a: good):
            publish.provenance(values,registry_data())
        for name, invalid in [('repository',dict(full_name='Other/Repository')),('path','.github/workflows/other.yml'),
                              ('event','push'),('conclusion','failure'),('head_branch','main')]:
            changed=copy.deepcopy(good)
            changed[name]=invalid
            with replace(publish,'api',lambda *a: changed):
                rejects(publish.provenance,values,registry_data(),text='provenance')
        replies=iter([dict(good,status='in_progress',conclusion=None),good])
        with replace(publish,'api',lambda *a: next(replies)), replace(publish.time,'sleep',lambda _: None):
            publish.provenance(values,registry_data())
        with replace(publish,'api',lambda *a: (_ for _ in ()).throw(AssertionError('API should not be called'))):
            rejects(publish.provenance,dict(values,build_repo='Wrong/Repo'),registry_data(),text='repository')
    print('provenance: repository, workflow, event, conclusion, branch and report race passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
