"""Single-target coordinator fixtures with real local Git transactions."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from ci import dispatch, repository
from ci.publish import publication


class PinnedJsonCase(unittest.TestCase):
    """Serve local pinned JSON for isolated format fixtures, without GitHub transport."""
    def setUp(self):
        repository.definition_data.cache_clear()
        self.addCleanup(repository.definition_data.cache_clear)

        def content(project, path, commit):
            self.assertEqual(path, 'ci/packages.json')
            self.assertRegex(commit, r'^[0-9a-f]{40}$')
            return json.dumps({k: v for k, v in repository.PROJECTS[project].items()
                               if not k.startswith('_')}).encode()

        context = patch.object(repository, 'content', side_effect=content)
        context.start()
        self.addCleanup(context.stop)
        return None


class CoordinatorCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root, self.bundle = self.base / 'feed', self.base / 'bundle'
        self.remote = self.base / 'remote.git'
        self.git('init', '--bare', '-b', 'main', str(self.remote))
        self.git('clone', str(self.remote), str(self.root))
        self.git('config', 'user.name', 'Test', cwd=self.root)
        self.git('config', 'user.email', 'test@example.invalid', cwd=self.root)
        self.graph = copy.deepcopy(repository.PROJECTS)
        self.row = next(r for r in publication.targets() if r['id'] == 'debian-trixie-amd64')
        self.sources = {p: {'refs/tags/v1.0.0': chr(97+i)*40} for i,p in enumerate(self.graph)}
        for project, config in self.graph.items():
            config['_commit'] = repository.source_commit(self.sources[project])
        self.context = dict(contract=3, projects={p: c for p, c in self.graph.items() if p in self.sources},
                            release_project='snode.c', run_id='100', run_url='capture', destination='SNodeC/Packages',
                            captured_at='2026-10-20T00:00:00Z', recipe_commit=self.git('rev-parse', 'HEAD', cwd=repository.ROOT))
        for name, value in dict(context=self.context, sources={self.row['id']:self.sources}, targets=[self.row], revisions=dict.fromkeys(self.graph, '2'), profiles={self.row['id']:dict(projects=self.graph, sources=self.sources, baseline={}, directory='debian/dists/trixie')}, checksums={}).items():
            publication.write(self.bundle / (name+'.json'), value)
        self.state = dict(repository='SNodeC/Packages', branch='main', counters={}, runs={})
        publication.record_run(self.bundle, self.state, self.context)
        self.save()
        self.runs, self.jobs, self.artifacts, self.posts = {}, {}, {}, []
        self.contents = {}
        repository.definition_data.cache_clear()
        self.addCleanup(repository.definition_data.cache_clear)
        for project, config in self.graph.items():
            self.contents['SNodeC/' + project, config['_commit'], 'ci/packages.json'] = json.dumps(
                {k: v for k, v in config.items() if not k.startswith('_')}).encode()
        self.runs[dispatch.COORDINATOR,100] = dict(event='workflow_dispatch',path='.github/workflows/orchestrate-packages.yml',head_repository={'full_name':dispatch.COORDINATOR})
        definitions = self.base / 'definitions.json'
        publication.write(definitions, dict(projects=self.graph, targets={self.row['id']:self.graph}))
        for context in [patch.dict(os.environ, CI_DEFINITIONS=str(definitions), GITHUB_REPOSITORY=dispatch.COORDINATOR,
                            GITHUB_WORKFLOW_REF=dispatch.COORDINATOR+'/.github/workflows/control-packages.yml@refs/heads/main',
                            COORDINATOR_ACTOR='ci[bot]', RUNNER_TEMP=str(self.base)),
                        patch.object(dispatch, 'api', side_effect=self.api), patch.object(dispatch, 'capacity', return_value=(20,{})),
                        patch.dict(repository.PROJECTS, self.graph, clear=True)]:
            context.start()
            self.addCleanup(context.stop)
        return None

    def git(self, *args, cwd=None):
        return subprocess.check_output(['git','-c','commit.gpgsign=false',*args], cwd=cwd or self.base, text=True, stderr=subprocess.DEVNULL).strip()

    def save(self):
        publication.write(self.root/'status.json', self.state)
        self.git('add','.',cwd=self.root)
        if subprocess.run(['git','diff','--cached','--quiet'],cwd=self.root).returncode:
            self.git('commit','-m','fixture',cwd=self.root)
            self.git('push','origin','HEAD:main',cwd=self.root)
        return None

    def node(self, project='snode.c', capture='100'):
        self.state = publication.read(self.root/'status.json')
        return self.state['runs'][capture].get('nodes',{}).get(self.row['id']+'/'+project,{})

    def tick(self, bundles=None):
        return dispatch.tick(self.root, bundles or {'100':self.bundle})

    def feed(self, projects, capture='100', revision='2'):
        info = dict(versions={self.graph[p]['package']:'1.0.0-'+revision+'~trixie' for p in projects}, sources={p:self.sources[p] for p in projects},
                    publications={p:dict(capture=capture, revision=revision, job_url='job-'+p, published_at='2026-10-20T00:00:00Z') for p in projects})
        publication.write(self.root/'debian/dists/trixie/build.json', {'targets':{'amd64':info}})
        self.state = publication.read(self.root/'status.json')
        self.save()
        return None

    def finish(self, artifact=True, conclusion='success'):
        node = self.node()
        repo, owner = 'SNodeC/snode.c', node['source']
        self.runs[repo,owner['run']].update(status='completed', conclusion=conclusion)
        self.jobs[repo,owner['run']][0].update(status='completed',conclusion=conclusion)
        if artifact:
            self.artifacts[repo,owner['run']] = [dict(id=1234,name=f'packages-snode.c-{self.row["id"]}-1', digest='sha256:'+'f'*64, expired=False, workflow_run={'id':owner['run']})]
        return node

    def api(self, endpoint, payload=None, token=None):
        parts = urlsplit(endpoint).path.split('/')
        repo = '/'.join(parts[1:3])
        value = {}
        if payload is not None:
            self.posts.append((endpoint,copy.deepcopy(payload)))
            request = json.loads(payload['inputs']['request'])
            number = 500+len(self.posts)
            publisher = parts[-2] == 'sign-and-publish-packages.yml'
            value = dict(workflow_run_id=number)
            self.runs[repo,number] = dict(id=number,event='workflow_dispatch',path='.github/workflows/'+parts[-2],
                display_title=('Publish · '+request['publish_intent']) if publisher else 'Packages · '+request['intent'],
                created_at=datetime.now(timezone.utc).isoformat(),head_repository={'full_name':repo},actor={'login':'ci[bot]'},run_attempt=1,status='queued',conclusion=None)
            self.jobs[repo,number] = [dict(id=number+1000,run_id=number,run_attempt=1,name='write' if publisher else 'build / '+request['target'],
                html_url=f'https://github.com/{repo}/actions/runs/{number}/job/{number+1000}',status='queued',runner_id=1,labels=['ubuntu-24.04'])]
        elif len(parts) == 3:
            value = dict(default_branch='main')
        elif '/contents/' in endpoint:
            path = '/'.join(parts[4:])
            ref = parse_qs(urlsplit(endpoint).query).get('ref', ['main'])[0]
            data = self.contents[repo, ref, path] if (repo, ref, path) in self.contents else (self.root/path).read_bytes() if ref == 'main' else self.git('show', ref + ':' + path, cwd=self.root).encode()
            value = dict(content=base64.b64encode(data).decode())
        elif parts[-1] == 'runs':
            entries = [r for (n,_),r in self.runs.items() if n==repo and r['path'].endswith(parts[-2])]
            created = parse_qs(urlsplit(endpoint).query).get('created', [''])[0]
            entries = [r for r in entries if not created or r.get('created_at', '') >= created.removeprefix('>=')]
            value = dict(total_count=len(entries), workflow_runs=entries)
        elif 'jobs' in parts:
            value = next(j for jobs in self.jobs.values() for j in jobs if j['id']==int(parts[-1])) if parts[-2]=='jobs' else dict(total_count=len(self.jobs.get((repo,int(parts[5])),[])),jobs=self.jobs.get((repo,int(parts[5])),[]))
        elif 'artifacts' in parts:
            value = next(a for items in self.artifacts.values() for a in items if a['id']==int(parts[-1])) if parts[-2]=='artifacts' else dict(total_count=len(self.artifacts.get((repo,int(parts[5])),[])),artifacts=self.artifacts.get((repo,int(parts[5])),[]))
        else:
            value = copy.deepcopy(self.runs[repo,int(parts[5])])
        page = int(parse_qs(urlsplit(endpoint).query).get('page', ['1'])[0])
        for field in ('workflow_runs', 'jobs', 'artifacts'):
            if field in value:
                value[field] = value[field][(page-1)*100:page*100]
        return copy.deepcopy(value)
