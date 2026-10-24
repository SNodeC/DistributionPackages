"""Single-target coordinator fixtures with real local Git transactions."""
import base64
import io
import tarfile
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

import offline

from ci import dispatch, repository
from ci.publish import publication


def feed_manifest(info, graph=None):
    """Construct the canonical version-addressed publication shape for fixtures."""
    graph = repository.PROJECTS if graph is None else graph
    value = copy.deepcopy(info)
    value['releases'] = {}
    for project, refs in value.get('sources', {}).items():
        tag = repository.source_tag(value, project)
        names = [n for n in value.get('packages', []) if repository.package_owner(n, graph) == project]
        files = {n: checksum for n, checksum in value.get('files', {}).items()
                 if repository.project_file(n, project, graph)}
        versions = {project: v for k, v in value.get('versions', {}).items() if k in {project, graph[project]['package']}}
        context = dict(value.get('context', {}))
        context.update(build_project=project, source_tags={project: tag}, versions={project: tag[1:]})
        receipt = value.get('publications', {}).get(project, {})
        release = next(iter(versions.values()), '')
        import re
        match = re.search(r'-r?(\d+)(?:[.~]|$)', release)
        revision = str(receipt.get('revision', value.get('revision', int(match[1]) if match else 0)))
        value['releases'][project] = {tag: dict(sources={project: refs}, revision=revision, context=context,
            versions=versions, files=files, unsigned_files=files, packages=names,
            publications={project: receipt}, published_at=(receipt.get('published_at') or value.get('published_at')
                if value.get('context', {}).get('build_project') == project else receipt.get('published_at')))}
    return value


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
        receipt = dict(capture='100', source=dict(run=42, attempt=1), job=43,
                       artifact=dict(id=44, digest='sha256:' + 'a' * 64),
                       job_url='https://github.com/SNodeC/snode.c/actions/runs/42/job/43')
        context = patch.dict(os.environ, BUILD_RECEIPT=json.dumps(receipt))
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
        self.bundles = {'100': self.bundle}
        self.context = dict(contract=3, projects={p: c for p, c in self.graph.items() if p in self.sources},
                            tag='v1.0.0', release_project='snode.c', run_id='100', run_url='capture', destination='SNodeC/Packages',
                            captured_at='2026-10-20T00:00:00Z', recipe_commit=self.git('rev-parse', 'HEAD', cwd=repository.ROOT))
        for name, value in dict(context=self.context, sources={self.row['id']:self.sources}, targets=[self.row],
            revisions={'snode.c': '2'}, profiles={self.row['id']:dict(projects=self.graph, sources=self.sources, baseline={},
            directory='debian/dists/trixie')}, checksums={}).items():
            publication.write(self.bundle / (name+'.json'), value)
        self.state = dict(repository='SNodeC/Packages', branch='main', counters={}, runs={},
            requests={p: {'v1.0.0': dict(definition=c, sha=c['_commit'], tag='v1.0.0', capture='100', revision='2')}
                      for p, c in self.graph.items()})
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
        return dispatch.tick(self.root, self.bundles | (bundles or {}))

    def add_capture(self, project, capture, revision='2', cause='release', cascade=None):
        """One canonical generation contains one selected project, as prepare() emits."""
        self.state = publication.read(self.root / 'status.json')
        directory = self.base / ('fixture-capture-' + capture)
        context = self.context | dict(run_id=capture, release_project=project, cause=cause,
                                      cascade=cascade or capture)
        info, path = publication.published(self.root, self.row)
        sources = copy.deepcopy(info.get('sources', {})) | {project: self.sources[project]}
        profile = dict(projects=self.graph, sources=sources, baseline=info, directory=path)
        for name, value in dict(context=context, targets=[self.row], sources={self.row['id']: sources},
                                revisions={project: revision}, profiles={self.row['id']: profile}, checksums={}).items():
            publication.write(directory / (name + '.json'), value)
        publication.record_run(directory, self.state, context)
        self.bundles[capture] = directory
        self.save()
        return directory

    def feed(self, projects, capture='100', revision='2'):
        info = dict(versions={self.graph[p]['package']:'1.0.0-'+revision+'~trixie' for p in projects}, sources={p:self.sources[p] for p in projects},
                    publications={p:dict(capture=capture, revision=revision, job_url='job-'+p, published_at='2026-10-20T00:00:00Z') for p in projects})
        publication.write(self.root/'debian/dists/trixie/build.json', {'targets':{'amd64':feed_manifest(info, self.graph)}})
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
            capturing = parts[-2] == 'orchestrate-packages.yml'
            value = dict(workflow_run_id=number)
            self.runs[repo,number] = dict(id=number,event='workflow_dispatch',path='.github/workflows/'+parts[-2],
                display_title=('Publish · '+request['publish_intent']) if publisher else ('Capture · ' if capturing else 'Packages · ')+request['intent'],
                created_at=datetime.now(timezone.utc).isoformat(),head_repository={'full_name':repo},actor={'login':'ci[bot]'},run_attempt=1,status='queued',conclusion=None)
            self.jobs[repo,number] = [dict(id=number+1000,run_id=number,run_attempt=1,
                name='write' if publisher else 'capture' if capturing else 'build / '+request['target'],
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


def ipk(path, name, version, arch='x86_64'):
    control = f'Package: {name}\nVersion: {version}\nArchitecture: {arch}\nDescription: real structure fixture\n'
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode='w:gz') as archive:
        entry = tarfile.TarInfo('./control')
        entry.size = len(control.encode())
        archive.addfile(entry, io.BytesIO(control.encode()))
    with tarfile.open(path, mode='w:gz') as archive:
        entry = tarfile.TarInfo('./control.tar.gz')
        entry.size = len(inner.getvalue())
        archive.addfile(entry, io.BytesIO(inner.getvalue()))
    return control
