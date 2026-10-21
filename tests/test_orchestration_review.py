"""Capture, retry and delayed-event regressions at the replacement boundaries."""
import copy
import json
import os
from pathlib import Path
from unittest.mock import patch
from support import CoordinatorCase
from ci import dispatch, repository
from ci.publish import publication


class ReviewTest(CoordinatorCase):
    def test_finalization_before_publication_does_not_fail_successful_handoffs(self):
        self.tick();self.finish(conclusion='failure');self.tick()
        self.assertEqual(self.node()['status'],'publishing')
        self.assertEqual(self.node()['artifact']['id'],1234)
        return None

    def test_retry_finalization_retains_earlier_handoffs_not_rerun(self):
        self.tick();node=self.finish(artifact=False,conclusion='failure');self.tick()
        repo='SNodeC/snode.c';number=node['source']['run']
        # An operator retry reopens the task, but carried jobs cannot become attempt-2 links.
        dispatch.transaction(self.root,dict(retry='100/snode.c/'+self.row['id']))
        self.tick()
        new=self.node();owner=new['source']['run']
        self.runs[repo,owner]['run_attempt']=2
        self.tick()
        self.assertNotIn('job_url',self.node())
        self.assertNotIn('job',self.node())
        self.jobs[repo,owner][0].update(run_attempt=2,html_url='real-attempt-2-job')
        self.tick()
        self.assertEqual(self.node()['job_url'],'real-attempt-2-job')
        return None

    def test_capture_owns_target_row_when_current_matrix_changes(self):
        self.tick()
        request=json.loads(self.posts[0][1]['inputs']['request'])
        with patch.object(publication,'targets',side_effect=AssertionError('use the capture')),patch.dict(os.environ,PACKAGE_REQUEST=json.dumps(request),BUILD_PROJECT='snode.c',GITHUB_OUTPUT=str(self.base/'out')),patch('sys.argv',['dispatch','authorize',str(self.bundle)]):
            dispatch.main()
        self.assertIn(self.row['id'],(self.base/'out').read_text())
        return None

    def test_finalizer_only_covers_its_requested_target(self):
        self.tick();self.finish(artifact=False,conclusion='cancelled');self.tick()
        self.assertEqual(self.node()['status'],'cancelled')
        self.assertNotEqual(self.node('mqttsuite')['status'],'cancelled')
        return None

    def test_event_type_and_canonical_run_ids_are_enforced(self):
        for value in ['0','01','-1','bad','1/attempts/2']:
            with self.subTest(value=value),self.assertRaises(ValueError):
                dispatch.identity(value)
        with patch.object(dispatch,'api',return_value=dict(event='push',path='.github/workflows/orchestrate-packages.yml',head_repository={'full_name':dispatch.COORDINATOR})),self.assertRaises(ValueError):
            dispatch.capture_run('100')
        return None

    def test_newer_published_application_is_not_left_pending_by_older_generation(self):
        self.feed(['snode.c','mqttsuite'],capture='newer',revision='3')
        self.tick()
        self.assertEqual(self.node('mqttsuite')['status'],'superseded')
        self.assertNotIn('mqttsuite',{json.loads(p['inputs']['request'])['project'] for _,p in self.posts})
        return None

    def test_missing_capture_is_retried_only_when_no_upload_succeeded(self):
        steps=[{'jobs':[{'steps':[dict(name='Save immutable release capture',conclusion='success')]}]}]
        with patch.dict(os.environ,GITHUB_RUN_ID='100',GITHUB_RUN_ATTEMPT='2'),patch.object(dispatch,'run',return_value=json.dumps(steps)),self.assertRaisesRegex(ValueError,'Previously saved capture'):
            dispatch.retry_capture()
        steps[0]['jobs'][0]['steps'][0]['conclusion']='failure'
        with patch.dict(os.environ,GITHUB_RUN_ID='100',GITHUB_RUN_ATTEMPT='2'),patch.object(dispatch,'run',return_value=json.dumps(steps)):
            dispatch.retry_capture()
        with patch.dict(os.environ,GITHUB_RUN_ATTEMPT='1'),patch.object(dispatch,'run') as command:
            dispatch.retry_capture()
            command.assert_not_called()
        return None

    def test_old_source_workflow_cannot_allocate_before_capture_fails(self):
        publication.write(self.root/'status.json',dict(counters={'snode.c':9},allocations={}))
        before=(self.root/'status.json').read_bytes()
        env=dict(RELEASE_PROJECT='snode.c',GITHUB_RUN_ID='123',GITHUB_REPOSITORY='SNodeC/snode.c',GITHUB_WORKFLOW_REF='source/workflow')
        with patch.dict(os.environ,env),patch('sys.argv',['publication','reserve',str(self.root)]),self.assertRaises(ValueError):
            publication.main()
        self.assertEqual((self.root/'status.json').read_bytes(),before)
        env.update(GITHUB_REPOSITORY=dispatch.COORDINATOR,GITHUB_WORKFLOW_REF=dispatch.COORDINATOR+'/.github/workflows/orchestrate-packages.yml@refs/heads/main')
        with patch.dict(os.environ,env),patch('sys.argv',['publication','reserve',str(self.root)]):
            publication.main()
        self.assertEqual(publication.read(self.root/'status.json')['counters']['snode.c'],10)
        return None
