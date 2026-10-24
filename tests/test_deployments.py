"""Two fresh deployments exercise one coordinator through local Git and mocked Actions."""
import base64
import copy
from contextlib import ExitStack, contextmanager, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import offline
from ci import dispatch, repository
from ci.publish import apt, publication


class DeploymentTest(unittest.TestCase):
    @contextmanager
    def deployment(self, owner, coordinator, feed_name, names, architectures=('amd64',)):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as temporary, ExitStack() as stack:
            self.base = Path(temporary)
            self.owner, self.coordinator, self.feed_name = owner, owner + '/' + coordinator, feed_name
            self.root = self.base / 'published'
            self.git('init', '--bare', '-b', 'stable', str(self.base / 'feed.git'))
            self.git('clone', str(self.base / 'feed.git'), str(self.root))
            self.git('config', 'user.name', 'Fixture', cwd=self.root)
            self.git('config', 'user.email', 'fixture@example.invalid', cwd=self.root)
            self.graph = {}
            for index, name in enumerate(names):
                required = [] if index == 0 else [names[0]] if index in {1, 2} else [names[1], names[2]]
                self.graph[name] = dict(title=name, package=name.replace('.', '-'), depends_on=required,
                    matrix={'linux': [dict(distribution='debian', suite='trixie', image='debian:trixie', architectures=list(architectures))]},
                    build={'native': 'ci/package/native.sh'})
                self.git('init', '--bare', '-b', 'source', str(self.base / (name + '.git')))
            self.row = repository.rows(self.graph[names[0]])[0]
            self.master = self.base / 'master.json'
            publication.write(self.master, dict(repositories=list(names), feed=dict(repository=feed_name, branch='stable')))
            self.runtime = self.base / 'definitions.json'
            publication.write(self.runtime, {'projects': {}})
            self.runs, self.jobs, self.artifacts, self.posts, self.bundles, self.outputs = {}, {}, {}, [], {}, {}
            self.number = 100
            self.handled = set()
            self.accesses = []
            self.keys = self.base / 'signing'
            (self.keys / 'keys').mkdir(parents=True)
            self.home = self.base / 'gnupg'
            self.home.mkdir(mode=0o700)
            repository.run('gpg', '--homedir', str(self.home), '--batch', '--pinentry-mode', 'loopback', '--passphrase', '',
                           '--quick-generate-key', 'Local <local@example.invalid>', 'rsa2048', 'sign', '1d', stderr=subprocess.DEVNULL)
            (self.keys / 'keys/apt.asc').write_text(repository.run('gpg', '--homedir', str(self.home), '--armor', '--export'))
            private = repository.run('gpg', '--homedir', str(self.home), '--batch', '--armor', '--export-secret-keys')
            stack.enter_context(patch.dict(os.environ, CI_MASTER=str(self.master), CI_DEFINITIONS=str(self.runtime),
                PACKAGE_COORDINATOR=self.coordinator, PACKAGE_COORDINATOR_REF='control', PYTHONPATH=str(repository.ROOT),
                GITHUB_REPOSITORY=self.coordinator, GITHUB_ACTOR='ci[bot]', GITHUB_TRIGGERING_ACTOR='ci[bot]',
                GITHUB_WORKFLOW_REF=self.coordinator + '/.github/workflows/orchestrate-packages.yml@refs/heads/control',
                GITHUB_RUN_ATTEMPT='1', COORDINATOR_ACTOR='ci[bot]', RUNNER_TEMP=str(self.base),
                GITHUB_OUTPUT=str(self.base / 'github-output'), APT_SIGNING_KEY=private,
                RELEASE_PARENT='', RELEASE_REQUESTED_AT='', GIT_ALLOW_PROTOCOL='file'))
            for module in (repository, dispatch, publication):
                for key, value in dict(COORDINATOR=self.coordinator, OWNER=owner, FEED=owner + '/' + feed_name,
                                       FEED_BRANCH='stable', REPOSITORIES=tuple(names)).items():
                    if hasattr(module, key):
                        stack.enter_context(patch.object(module, key, value))
            for module in (repository, dispatch):
                stack.enter_context(patch.object(module, 'COORDINATOR_NAME', coordinator))
                stack.enter_context(patch.object(module, 'CONFIG', repository.load_master(self.master)))
            stack.enter_context(patch.object(repository, 'DEFINITIONS', self.runtime))
            stack.enter_context(patch.dict(repository.PROJECTS, {}, clear=True))
            stack.enter_context(patch.dict(repository.ROW_PROJECTS, {}, clear=True))
            stack.enter_context(patch.object(repository, 'run', side_effect=self.local_run))
            stack.enter_context(patch.object(repository, 'content', side_effect=self.content))
            stack.enter_context(patch.object(dispatch, 'content', side_effect=self.content))
            stack.enter_context(patch.object(dispatch, 'api', side_effect=self.api))
            stack.enter_context(patch.object(dispatch, 'capacity', return_value=(40, {})))
            stack.enter_context(patch.object(repository, 'fetch', side_effect=self.fetch))
            stack.enter_context(patch.object(apt, 'ROOT', self.keys))
            stack.enter_context(patch.object(publication, 'ROOT', self.keys))
            # The shell CAS writer still executes the actual coordinator module.
            self.real_root = repository.ROOT
            repository.definition_data.cache_clear()
            previous = Path.cwd()
            os.chdir(self.base)
            try:
                publication.write(self.root / 'status.json', dict(repository=owner + '/' + feed_name, branch='stable', runs={}))
                self.commit()
                yield
            finally:
                os.chdir(previous)
                repository.definition_data.cache_clear()

    def git(self, *args, cwd=None, input=None):
        result = subprocess.check_output(['git', '-c', 'commit.gpgsign=false', *args], cwd=cwd or self.base,
                                         input=input, stderr=subprocess.DEVNULL)
        return result.decode().strip()

    def commit(self):
        self.git('add', '.', cwd=self.root)
        if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=self.root).returncode:
            self.git('commit', '-m', 'fixture publication', cwd=self.root)
            self.git('push', 'origin', 'HEAD:stable', cwd=self.root)
        return None

    def tag(self, project, tag, marker='original'):
        # Bare fixture creation writes no extra source checkout.
        config = self.graph[project]
        hook = '''set -eu
mkdir -p packages payload/DEBIAN
printf 'Package: %s\\nVersion: %s\\nArchitecture: %s\\nMaintainer: Local <local@example.invalid>\\nDescription: %s\\n' \\
    "$PACKAGE_NAME" "$PACKAGE_VERSION" "$PACKAGE_ARCH" "$MARKER" > payload/DEBIAN/control
dpkg-deb --build --root-owner-group payload "packages/${PACKAGE_NAME}_${PACKAGE_VERSION}_${PACKAGE_ARCH}.deb"
printf '%s\\n' "$PACKAGE_NAME" > "packages/${PACKAGE_NAME}.packages"
'''
        files = {'ci/packages.json': json.dumps(config), 'VERSION': tag[1:] + '\n', 'ci/package/native.sh': hook,
                 '.github/workflows/build-distribution-packages.yml': 'fixture wrapper at selected tag\n', 'marker': marker}
        stream = 'commit refs/heads/source\ncommitter Fixture <fixture@example.invalid> 1792500000 +0000\ndata 7\nfixture\ndeleteall\n'
        for path, value in files.items():
            stream += 'M 100644 inline ' + path + '\ndata ' + str(len(value.encode())) + '\n' + value + '\n'
        self.git('fast-import', '--quiet', '--force', cwd=self.base / (project + '.git'), input=stream.encode())
        commit = self.git('rev-parse', 'source', cwd=self.base / (project + '.git'))
        self.git('update-ref', 'refs/tags/' + tag, commit, cwd=self.base / (project + '.git'))
        return commit

    def local_run(self, *args, **kwargs):
        converted = []
        for arg in args:
            prefix = 'https://github.com/' + self.owner + '/'
            converted.append(str(self.base / (str(arg)[len(prefix):])) if str(arg).startswith(prefix) else arg)
        return repository_run(*converted, **kwargs)

    def content(self, project, path, commit):
        self.accesses.append(('contents', project, path, commit))
        source = self.base / ('feed.git' if project == self.feed_name else project + '.git')
        return subprocess.check_output(['git', 'show', commit + ':' + path], cwd=source, stderr=subprocess.DEVNULL)

    def fetch(self, url, destination=None):
        parts = urlsplit(url).path.split('/')
        data = self.content(parts[2], '/'.join(parts[4:]), parts[3])
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        return data

    def api(self, endpoint, payload=None, token=None):
        self.accesses.append(('api', endpoint))
        parts = urlsplit(endpoint).path.split('/')
        repo = '/'.join(parts[1:3])
        result = {}
        if payload is not None:
            self.number += 1
            request = json.loads(payload['inputs']['request'])
            workflow = parts[-2]
            kind = 'publish' if workflow == 'sign-and-publish-packages.yml' else request.get('kind', 'build')
            title = (('Publish · ' + request['publish_intent']) if kind == 'publish'
                     else ('Capture · ' if kind == 'capture' else 'Packages · ') + request['intent'])
            self.runs[repo, self.number] = dict(id=self.number, event='workflow_dispatch', path='.github/workflows/' + workflow,
                display_title=title, actor={'login': 'ci[bot]'}, head_repository={'full_name': repo}, status='queued',
                conclusion=None, run_attempt=1, created_at='2026-10-21T00:00:00Z')
            self.jobs[repo, self.number] = [dict(id=self.number + 10000, run_id=self.number, run_attempt=1,
                name='write' if kind == 'publish' else 'capture' if kind == 'capture' else 'build / ' + request['target'],
                html_url=f'https://github.com/{repo}/actions/runs/{self.number}/job/{self.number + 10000}', status='queued', runner_id=0)]
            self.posts.append((self.number, repo, kind, request))
            result = dict(workflow_run_id=self.number)
        elif len(parts) == 3:
            result = dict(default_branch='control' if repo == self.coordinator else 'source')
        elif 'contents' in parts:
            ref = parse_qs(urlsplit(endpoint).query)['ref'][0]
            result = dict(content=base64.b64encode(self.content(parts[2], '/'.join(parts[4:]), ref)).decode())
        elif parts[-1] == 'jobs':
            entries = self.jobs[repo, int(parts[5])]
            result = dict(jobs=entries, total_count=len(entries))
        elif parts[-2] == 'jobs':
            result = next(j for jobs in self.jobs.values() for j in jobs if j['id'] == int(parts[-1]))
        elif parts[-1] == 'artifacts':
            entries = self.artifacts.get((repo, int(parts[5])), [])
            result = dict(artifacts=entries, total_count=len(entries))
        elif parts[-2] == 'artifacts':
            result = next(a for entries in self.artifacts.values() for a in entries if a['id'] == int(parts[-1]))
        else:
            result = self.runs[repo, int(parts[5])]
        return copy.deepcopy(result)

    def capture(self, payload, number):
        with patch.dict(os.environ, GITHUB_RUN_ID=str(number),
                        GITHUB_WORKFLOW_REF=self.coordinator + '/.github/workflows/orchestrate-packages.yml@refs/heads/control'):
            release = dispatch.intake(payload)
            if release['duplicate'] == 'false':
                env = {'RELEASE_' + k.upper(): str(release[k]) for k in ('project', 'tag', 'sha', 'run', 'requested_at', 'parent', 'cause')}
                with patch.dict(os.environ, env):
                    # subprocess imports the configured definitions and commits the required CAS allocation.
                    repository_run('bash', str(self.real_root / 'ci/publish/status.sh'), str(self.root), 'reserve')
                    bundle = self.base / ('capture-' + str(number))
                    repository.prepare(self.root, bundle)
                    self.bundles[str(number)] = bundle
                    with patch('sys.argv', ['publication', 'status', str(self.root), str(bundle), '-', '-', 'pending']):
                        publication.main()
                    self.commit()
        return None

    def notify(self, project, tag, commit):
        self.number += 1
        number = self.number
        self.runs[self.owner + '/' + project, number] = dict(event='push', path='.github/workflows/build-distribution-packages.yml',
            head_repository={'full_name': self.owner + '/' + project}, head_branch=tag, head_sha=commit,
            created_at=f'2026-10-21T00:{number // 60:02}:{number % 60:02}Z')
        payload = dict(project=project, tag=tag, sha=commit, run=str(number), definition=self.content(project, 'ci/packages.json', commit).decode())
        self.number += 1
        self.runs[self.coordinator, self.number] = dict(event='workflow_dispatch', path='.github/workflows/orchestrate-packages.yml',
            head_repository={'full_name': self.coordinator}, status='completed')
        self.capture(payload, self.number)
        return str(self.number), payload

    def drain(self):
        handled = self.handled
        rounds = 0
        while rounds < 40:
            rounds += 1
            with patch.dict(os.environ, GITHUB_WORKFLOW_REF=self.coordinator + '/.github/workflows/control-packages.yml@refs/heads/control'):
                dispatch.tick(self.root, self.bundles)
            pending = [p for p in self.posts if p[0] not in handled]
            if not pending:
                break
            for number, repo, kind, request in pending:
                handled.add(number)
                bundle = self.bundles[request['capture']]
                if kind == 'capture':
                    self.capture(request, number)
                elif kind == 'build':
                    self.build(number, repo, request, bundle)
                else:
                    self.publish(number, request, bundle)
                self.runs[repo, number].update(status='completed', conclusion='success')
                self.jobs[repo, number][0].update(status='completed', conclusion='success')
                if getattr(self, 'unchanged_pages', None) is not None:
                    self.assertEqual(self.pages(), self.unchanged_pages, 'Older callback/publication must preserve every visible page')
        self.assertLess(rounds, 40, 'Unbounded duplicate dispatch loop')
        return None

    def build(self, number, repo, request, bundle):
        row = next(r for r in publication.read(bundle / 'targets.json') if r['id'] == request['target'])
        directory = self.base / ('build-' + str(number))
        directory.mkdir()
        original_bundle = bundle
        bundle = directory / 'bundle'
        shutil.copytree(original_bundle, bundle)
        profile = publication.read(bundle / 'profiles.json')[row['id']]
        with patch.dict(os.environ, PACKAGE_REQUEST=json.dumps(request), BUILD_PROJECT=request['project'], GITHUB_REPOSITORY=repo,
                        PUBLISHED_REF=request['publication'], PACKAGE_RELEASE=publication.read(bundle / 'revisions.json')[request['project']]):
            with patch('sys.argv', ['dispatch', 'authorize', str(bundle)]):
                dispatch.main()
            dispatch.baseline(bundle, row['id'], request['publication'])
            baseline = publication.read(Path('published-baseline/build.json'))
            repository.select(bundle, row['id'], request['project'], baseline)
            repository.reuse(bundle, row['id'], directory / 'dependencies')
            profile = publication.read(bundle / 'profiles.json')[row['id']]
            archive = bundle / 'archives' / profile['archives'][request['project']]
            source = directory / 'source'
            source.mkdir()
            with tarfile.open(archive) as stream:
                stream.extractall(source, filter='data')
            selected = next(source.iterdir())
            version = profile['context']['versions'][request['project']]
            package = self.graph[request['project']]['package']
            env = os.environ | dict(PACKAGE_ARCH=row['arch'], PACKAGE_NAME=package,
                PACKAGE_VERSION=repository.package_version(row, version, os.environ['PACKAGE_RELEASE']),
                MARKER=(selected / 'marker').read_text())
            # Execute the actual native wrapper, with host package/user administration mocked.
            # Only its /work mount is mapped to this disposable fixture; product compilation stays source-owned.
            script = (self.real_root / 'ci/build/native.sh').read_text()
            script = script.replace('/work/feed', str(self.real_root)).replace('/work', str(directory))
            administration = ('apt-get() { return 0; }\nldconfig() { return 0; }\nuseradd() { return 0; }\n'
                              'cmake() { return 99; }\nninja() { return 99; }\ncpack() { return 99; }\n')
            script = script.replace('case ', administration + 'case ', 1)
            fixture = directory / 'native-fixture.sh'
            fixture.write_text(script)
            repository_run('bash', str(fixture), cwd=directory, env=env | dict(DISTRIBUTION='debian', SUITE='trixie'))
            output = directory / 'output'
            apt.stage('trixie', directory / 'packages', bundle, output / 'linux', 'debian')
            self.outputs[number] = output
        artifact = dict(id=number + 20000, name=f'packages-{request["project"]}-{request["target"]}-1',
                        digest='sha256:' + hashlib.sha256(str(number).encode()).hexdigest(), expired=False, workflow_run={'id': number})
        self.artifacts[repo, number] = [artifact]
        self.jobs[repo, number][0].update(status='completed')
        callback = request | dict(status='publishing', run=number, attempt=1, job=number + 10000,
                                  artifact={k: artifact[k] for k in ('id', 'digest')})
        with patch.dict(os.environ, GITHUB_WORKFLOW_REF=self.coordinator + '/.github/workflows/control-packages.yml@refs/heads/control'):
            dispatch.apply_report(self.root, callback, original_bundle)
        return None

    def publish(self, number, request, bundle):
        row = next(r for r in publication.read(bundle / 'targets.json') if r['id'] == request['target'])
        values = dispatch.receive(request, bundle)
        self.git('sparse-checkout', 'disable', cwd=self.root)
        previous = self.git('rev-parse', 'HEAD', cwd=self.root)
        with tempfile.TemporaryDirectory(dir=self.base) as temporary:
            incoming = Path(temporary) / 'incoming'
            shutil.copytree(self.outputs[request['run']], incoming)
            overlay = Path(temporary)/'current'
            authored = Path(getattr(self,'site',os.environ.get('PACKAGE_SITE',self.real_root/'site')))
            shutil.copytree(authored,overlay/'site')
            shutil.copytree(authored.parent/'install',overlay/'install')
            shutil.copytree(self.keys/'keys',overlay/'keys')
            with patch.dict(os.environ, BUILD_RECEIPT=values['receipt'], BUILD_BASELINE=values['baseline'],
                            PUBLISHED_REF=request['publication'], PACKAGE_SITE=str(overlay/'site'),
                            BUILD_ATTEMPT=str(request['attempt']), BUILD_RUN_URL=values['run_url']), \
                    patch('sys.argv', ['publication', 'feed', str(self.root), str(bundle), json.dumps(row),
                                       request['project'], str(incoming)]):
                errors = io.StringIO()
                with redirect_stderr(errors):
                    result = publication.main()
                if result:
                    raise RuntimeError(errors.getvalue())
                repository.run('bash', str(self.real_root / 'ci/publish/push.sh'), str(self.root), previous, 'Fixture publication',
                               'python3', '-m', 'ci.publish.publication', 'status', str(self.root), str(bundle),
                               json.dumps(row), request['project'], 'published')
        self.git('fetch', 'origin', 'stable', cwd=self.root)
        self.git('reset', '--hard', 'FETCH_HEAD', cwd=self.root)
        return None

    def pages(self):
        self.git('sparse-checkout', 'disable', cwd=self.root)
        with patch.object(publication, 'ROOT', self.real_root):
            publication.copy_site(self.root)
            publication.render(self.root, publication.read(self.root / 'status.json'))
        value = {str(p.relative_to(self.root)): p.read_bytes() for p in (self.root / 'status').rglob('*') if p.is_file()}
        value['README.md'] = (self.root / 'README.md').read_bytes()
        self.commit()
        return value

    def exercise(self, owner, coordinator, feed, names):
        files = [p for folder in ('ci', '.github/workflows') for p in (repository.ROOT / folder).rglob('*')
                 if p.is_file() and p.suffix in {'.py', '.sh', '.yml', '.tmpl'}]
        before = {str(p.relative_to(repository.ROOT)): repository.digest(p) for p in files}
        with self.deployment(owner, coordinator, feed, names):
            root, app, sibling, join = names
            first, payload = self.notify(root, 'v1.0.0', self.tag(root, 'v1.0.0'))
            self.drain()
            self.assertEqual(set(publication.published(self.root, self.row)[0]['sources']), {root})
            self.assertFalse(any(app in str(a) or sibling in str(a) for a in self.accesses))
            start = len(self.posts)
            direct, _ = self.notify(app, 'v2.0.0', self.tag(app, 'v2.0.0'))
            self.drain()
            self.assertEqual([r['capture'] for _, _, k, r in self.posts[start:] if k == 'build'], [direct])
            self.assertEqual([r for _, _, k, r in self.posts[start:] if k == 'capture'], [])
            high = publication.published(self.root, self.row)[0]['releases'][app]['v2.0.0']
            self.assertEqual(high['context']['source_tags'][app], 'v2.0.0')
            self.assertEqual(high['publications'][app]['capture'], direct)
            highest_pages = self.pages()
            self.notify(app, 'v1.9.0', self.tag(app, 'v1.9.0'))
            self.assertEqual(self.pages(), highest_pages, 'Older pending capture must not change displayed highest status')
            self.unchanged_pages = highest_pages
            self.drain()
            self.assertEqual(self.pages(), highest_pages)
            self.unchanged_pages = None
            info = publication.published(self.root, self.row)[0]
            self.assertEqual(set(info['releases'][app]), {'v1.9.0', 'v2.0.0'})
            self.assertEqual(repository.source_tag(info, app), 'v2.0.0')
            self.assertEqual(publication.projection(publication.read(self.root / 'status.json'))['latest'][app]['tag'], 'v2.0.0')
            self.notify(sibling, 'v1.0.0', self.tag(sibling, 'v1.0.0'))
            self.drain()
            self.notify(join, 'v1.0.0', self.tag(join, 'v1.0.0'))
            self.drain()
            start = len(self.posts)
            self.notify(root, 'v1.0.0', self.tag(root, 'v1.0.0', 'moved root'))
            self.drain()
            captures = [r for _, _, kind, r in self.posts[start:] if kind == 'capture']
            self.assertEqual(sorted(r['project'] for r in captures), sorted([app, sibling, join]))
            join_capture = next(number for number, _, kind, r in self.posts[start:] if kind == 'capture' and r['project'] == join)
            arm_publications = [number for number, _, kind, r in self.posts[start:] if kind == 'publish' and r['project'] in {app, sibling}]
            self.assertEqual(len(arm_publications), 2)
            self.assertGreater(join_capture, max(arm_publications))
            builds = [r for _, _, kind, r in self.posts[start:] if kind == 'build' and r['project'] == app]
            self.assertEqual(len(builds), 1)
            app_profile = publication.read(self.bundles[builds[0]['capture']] / 'profiles.json')[self.row['id']]
            self.assertEqual(app_profile['context']['source_tags'][app], 'v2.0.0')
            self.assertEqual(publication.projection(publication.read(self.root / 'status.json'))['latest'][app]['tag'], 'v2.0.0')
            self.git('sparse-checkout', 'disable', cwd=self.root)
            self.assertTrue((self.root / 'debian/dists/trixie/InRelease').is_file())
            self.assertTrue((self.root / 'debian/dists/trixie/Release.gpg').is_file())
        self.assertEqual(before, {str(p.relative_to(repository.ROOT)): repository.digest(p) for p in files})
        if os.environ.get('PACKAGE_TEST_DEPLOYMENT_PROOF'):
            proof = Path(os.environ['PACKAGE_TEST_DEPLOYMENT_PROOF'] + '.' + owner + '.json')
            with proof.open('x') as stream:
                json.dump(dict(owner=owner, coordinator=coordinator, feed=feed, code=before), stream, indent=2)
        return before

    def test_snodec_first_deployment_and_independent_non_cmake_deployment(self):
        first = self.exercise('SNodeC', 'DistributionPackages', 'Packages', ('snode.c', 'mqttsuite', 'snode.c-idp', 'join'))
        second = self.exercise('ExampleOrg', 'ReleaseControl', 'Binaries', ('engine', 'client', 'plugin', 'bundle'))
        self.assertEqual(first, second, 'Both deployments must execute byte-identical coordinator production code')
        return None


repository_run = repository.run
