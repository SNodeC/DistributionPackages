"""Status pages exercise authoritative filesystem facts, not remote publication."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from ci import repository
from ci.publish import publication

class PackagePagesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = next(row for row in publication.targets() if row['distribution'] == 'openwrt')
        self.key = self.row['id']
        self.generation = dict(revisions={'snode.c': '9', 'mqttsuite': '9'}, run_id='capture', run_url='url',
                               context={'captured_at': '2026-10-10T10:00:00Z'},
                               sources={'snode.c': {'refs/tags/v2.0.0': 'sha'}, 'mqttsuite': {'refs/tags/v1.0.2': 'sha'}})
        self.state = dict(targets={}, runs={'capture': self.generation})
        self.feed = self.root / publication.feed_paths(self.row)[0] / 'build.json'
        publication.write(self.feed, dict(versions={'snodec': '2.0.0-r8', 'mqttsuite': '1.0.2-r8'},
                                         context={'build_project': 'mqttsuite', 'captured_at': '2026-10-09T09:00:00Z'},
                                         published_at='2026-10-09T12:00:00Z'))
        shutil.copy2(repository.ROOT/'site/README.md', self.root/'README.md')
    def event(self, project, status, time, attempt=1, stage='build'):
        with patch.dict(os.environ, EVENT_TIME=time, EVENT_STAGE=stage):
            publication.update(self.state, self.row, self.generation, project, status, attempt)
    def text(self, package='snodec'):
        return (self.root/f'status/{package}.md').read_text()
    def test_deterministic_projection_preserves_state_feeds_and_full_target_coverage(self):
        self.event('snode.c', 'running', '2026-10-10T11:00:00Z')
        before=copy.deepcopy(self.state); feed=self.feed.read_bytes()
        publication.render(self.root,self.state)
        first={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        publication.render(self.root,self.state)
        self.assertEqual(first,{p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(before,self.state); self.assertEqual(feed,self.feed.read_bytes())
        for package in ['snodec','mqttsuite']:
            self.assertEqual(sum(line.startswith('| '+chr(96)) for line in self.text(package).splitlines()),len(publication.targets()))
        self.assertIn('## Needs attention', self.text()); self.assertNotIn('<details>',self.text())
    def test_versions_capture_and_publication_times_are_project_specific(self):
        self.event('snode.c','running','2026-10-10T11:00:00Z')
        publication.render(self.root,self.state)
        for text in ['2.0.0-r8','v2.0.0','r9 · attempt 1','Captured: 2026-10-10 10:00 UTC','Started: 2026-10-10 11:00 UTC']:
            self.assertIn(text,self.text())
        self.assertNotIn('2026-10-09 12:00 UTC',self.text())
        self.assertIn('2026-10-09 12:00 UTC',self.text('mqttsuite'))
    def test_publication_time_survives_new_attempt(self):
        self.event('snode.c','published','2026-10-10T12:00:00Z',stage='publication')
        info=publication.read(self.feed); info['versions']['snodec']='2.0.0-r9'; publication.write(self.feed,info)
        self.generation=self.generation | dict(run_id='next',revisions={'snode.c':'10'});self.state['runs']['next']=self.generation
        self.event('snode.c','running','2026-10-11T12:00:00Z')
        publication.render(self.root,self.state)
        self.assertIn('Published: 2026-10-10 12:00 UTC',self.text())
        self.assertIn('Started: 2026-10-11 12:00 UTC',self.text())
        self.assertNotIn('Published: 2026-10-11 12:00 UTC',self.text())
    def test_old_writer_cannot_attach_stale_metadata_to_new_state(self):
        self.event('snode.c','running','2026-10-10T11:00:00Z')
        self.state['targets'][self.key+'/snode.c']['status']='publishing'
        publication.render(self.root,self.state)
        self.assertIn('Built: not recorded',self.text())
        self.assertNotIn('Built: 2026-10-10 11:00 UTC',self.text())
    def test_replayed_regressive_terminal_events_do_not_change_metadata(self):
        self.event('snode.c','running','2026-10-10T11:00:00Z'); before=copy.deepcopy(self.state)
        self.event('snode.c','running','2026-10-10T11:05:00Z');self.event('snode.c','pending','2026-10-10T11:06:00Z')
        self.assertEqual(before,self.state)
        self.event('snode.c','published','2026-10-10T12:00:00Z',stage='publication');before=copy.deepcopy(self.state)
        self.event('snode.c','failed','2026-10-10T13:00:00Z');self.assertEqual(before,self.state)
    def test_failure_stage_and_retry(self):
        self.event('snode.c','running','2026-10-10T11:00:00Z');self.event('snode.c','failed','2026-10-10T11:10:00Z')
        publication.render(self.root,self.state);self.assertIn('Build failed',self.text())
        self.event('snode.c','running','2026-10-10T12:00:00Z',2)
        self.event('snode.c','publishing','2026-10-10T12:10:00Z',2)
        self.event('snode.c','failed','2026-10-10T12:20:00Z',2,'publication')
        publication.render(self.root,self.state);self.assertIn('Publication failed',self.text())
        self.assertEqual(self.state['timeline'][self.key+'/snode.c']['event']['started_at'],'2026-10-10T12:00:00Z')
    def test_unknown_historical_failure_stage_not_invented(self):
        self.state['targets'][self.key+'/snode.c']=dict(status='failed',revision='8',attempt=1)
        publication.render(self.root,self.state);self.assertIn('Failed · stage not recorded',self.text())
    def test_dependency_retry_displays_waiting_without_new_state(self):
        self.event('snode.c','failed','2026-10-10T11:00:00Z');self.event('mqttsuite','skipped','2026-10-10T11:00:00Z',0)
        publication.render(self.root,self.state)
        self.assertIn('Skipped · SNode.C: failed',self.text('mqttsuite'))
        self.event('snode.c','running','2026-10-10T12:00:00Z',2);before=copy.deepcopy(self.state)
        publication.render(self.root,self.state);self.assertIn('Waiting for SNode.C',self.text('mqttsuite'))
        self.assertEqual(before,self.state)
    def test_third_project_without_template_branch(self):
        with patch.dict(repository.PROJECTS,{'new-project':dict(title='New project',package='new-package',depends_on=())}):
            publication.render(self.root,self.state)
        self.assertTrue((self.root/'status/new-package.md').exists())
        self.assertIn('[New project](new-package.md#page-overview)',(self.root/'status/README.md').read_text())
    def test_legacy_anchors_and_authored_text(self):
        (self.root/'README.md').write_text((self.root/'README.md').read_text()+'\nAUTHORED SENTINEL\n')
        publication.render(self.root,self.state);legacy=(self.root/'docs/status.md').read_text()
        for anchor in ['2410','2512','trixie','trixie-1','debian-trixie','rocky-linux-9']:
            self.assertIn(f'<a id="{anchor}"></a>',legacy)
        self.assertNotIn('| Architecture',legacy)
        self.assertIn('AUTHORED SENTINEL',(self.root/'README.md').read_text())
    def test_current_doc_overlay_preserves_capture_pinned_executables(self):
        workflow=(repository.ROOT/'.github/workflows/release.yml').read_text()
        shell=workflow.split('          # Separate authored presentation',1)[1].split('\n',1)[1].split("          echo 'paths<<EOF'",1)[0]
        shell=shell.replace('$DOCS_BRANCH','trunk')
        current=self.root/'feed';current.mkdir()
        def git(*args):return subprocess.check_output(['git','-c','commit.gpgsign=false','-C',str(current),*args],text=True).strip()
        git('init','-b','trunk');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
        (current/'docs').mkdir();(current/'docs/old.md').write_text('old');(current/'README.md').write_text('old');(current/'tool.py').write_text('CAPTURED')
        git('add','.');git('commit','-m','capture');commit=git('rev-parse','HEAD')
        shutil.copytree(repository.ROOT/'site',current/'site');(current/'tool.py').write_text('NEW')
        git('add','.');git('commit','-m','current');git('update-ref','refs/remotes/origin/trunk','HEAD')
        tmp=self.root/'runner';tmp.mkdir()
        env=os.environ | {'RUNNER_TEMP':str(tmp),'GITHUB_ENV':str(self.root/'env')}
        subprocess.run(['bash','-e','-o','pipefail','-c','commit='+commit+'\n'+shell],cwd=self.root,env=env,check=True,capture_output=True)
        self.assertEqual((current/'README.md').read_bytes(),(repository.ROOT/'site/README.md').read_bytes())
        self.assertFalse((current/'docs/old.md').exists());self.assertEqual((current/'tool.py').read_text(),'CAPTURED')

if __name__ == '__main__': unittest.main()
