"""Authenticated release intake and build/publication handoffs owned by the coordinator."""
import hashlib
import zipfile
import copy
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import uuid
from urllib.parse import urlencode

from ci.repository import PROJECTS, REPOSITORIES, ROOT, CONFIG, supports, run, project_revision, configure, activate, dependencies, source_commit, binding, content, bind_projects, digest, missing_prerequisites
from ci.repository import ownership
from ci.publish.publication import read, write, published, TERMINAL

COORDINATOR = 'SNodeC/DistributionPackages'
TAG = r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
SHA = r'[0-9a-f]{40}'


def api(path, payload=None, token=None):
    token = token or (os.environ.get('PACKAGES_TOKEN') if path.startswith('repos/SNodeC/Packages/') else None)
    args = ['gh', 'api', '--include', '-H', 'X-GitHub-Api-Version: 2026-03-10', path]
    if payload is not None:
        args += ['--method', 'POST', '--input', '-']
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None, text=True, capture_output=True, timeout=120, env=os.environ | (dict(GH_TOKEN=token) if token else {}))
    headers, _, body = result.stdout.replace('\r\n', '\n').partition('\n\n')
    status = re.search(r'HTTP/[\d.]+ (\d+)', headers)
    if result.returncode:
        retry = re.search(r'(?im)^retry-after: ([0-9]+)', headers)
        reset = re.search(r'(?im)^x-ratelimit-reset: ([0-9]+)', headers)
        limited = bool(retry or re.search(r'(?im)^x-ratelimit-remaining: 0$', headers))
        delay = int(retry[1]) if retry else max(0, int(reset[1]) - time.time()) if reset and limited else 0
        raise ApiError(int(status[1]) if status else 0, path + ': ' + ('rate limit: ' if limited else '') + result.stderr + body, min(1800, delay))
    return json.loads(body) if body.strip() else None


class ApiError(RuntimeError):
    def __init__(self, status, message, retry_after=0):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        return None


def listing(path, field, token=None):
    rows, page, more = [], 1, True
    while more:
        value = api(path + ('&' if '?' in path else '?') + f'per_page=100&page={page}', token=token)
        if not isinstance(value, dict) or value.get('total_count', 0) >= 1000:
            raise ValueError('API search is malformed or truncated; refusing to infer absence: ' + path)
        rows.extend(value[field])
        more = len(value[field]) == 100
        page += 1
    return rows


def identity(value):
    result = str(value)
    if not re.fullmatch(r'[1-9][0-9]*', result):
        raise ValueError('Invalid run identity')
    return result


def intake(payload):
    project, tag, sha = payload['project'], payload['tag'], payload['sha']
    if project not in REPOSITORIES or not re.fullmatch(TAG, tag) or not re.fullmatch(SHA, sha):
        raise ValueError('Release needs a registered project, version tag and exact commit')
    origin = api(f'repos/SNodeC/{project}/actions/runs/{identity(payload["run"])}')
    if (origin['event'] != 'push' or origin['path'] != '.github/workflows/build-distribution-packages.yml'
            or origin['head_repository']['full_name'] != f'SNodeC/{project}'
            or origin['head_branch'] != tag or origin['head_sha'] != sha):
        raise ValueError('Release notification does not match the upstream tag workflow')
    previous = read(Path('published/status.json'), {}).get('requests', {}).get(project, {})
    duplicate = str(previous.get('run', '')) == str(payload['run']) and previous.get('capture') != os.environ.get('GITHUB_RUN_ID')
    duplicate = duplicate or (previous.get('at', ''), int(previous.get('run', 0))) > (origin['created_at'], int(payload['run']))
    configure(Path('published'), project, sha, json.loads(payload['definition']))
    return dict(project=project, tag=tag, sha=sha, duplicate=str(duplicate).lower(), requested_at=origin['created_at'], run=payload['run'])


def capture_run(capture):
    origin = api(f'repos/{COORDINATOR}/actions/runs/{identity(capture)}')
    if (origin['event'] != 'workflow_dispatch' or origin['path'] != '.github/workflows/orchestrate-packages.yml'
            or origin['head_repository']['full_name'] != COORDINATOR):
        raise ValueError('Capture must belong to the coordinator workflow')
    return origin


def retry_capture():
    for attempt in range(1, int(os.environ['GITHUB_RUN_ATTEMPT'])):
        pages = json.loads(run('gh', 'api', '--paginate', '--slurp',
            f'repos/{COORDINATOR}/actions/runs/{identity(os.environ["GITHUB_RUN_ID"])}/attempts/{attempt}/jobs?per_page=100'))
        if any(step['name'] == 'Save immutable release capture' and step.get('conclusion') == 'success'
               for page in pages for job in page['jobs'] for step in job.get('steps', [])):
            raise ValueError('Previously saved capture is unavailable; refusing to recapture this generation')


def ready(profile, revisions, project, info, projects=None):
    projects = PROJECTS if projects is None else projects
    result = True
    for dependency in dependencies(project, projects):
        revision = project_revision(info, dependency, projects)
        expected = int(revisions.get(dependency, 0))
        result = result and source_commit(info.get('sources', {}).get(dependency)) is not None and revision >= expected
        if expected and revision == expected:
            result = result and info['sources'].get(dependency) == profile['sources'].get(dependency)
        if expected and revision > expected and not CONFIG['settings']['rebuild_overlap']:
            result = False
    return result


def baseline(bundle, target, ref):
    from ci.repository import fetch
    activate(bundle, target)
    if not re.fullmatch(SHA, ref):
        raise ValueError('Dependencies require an exact publication commit')
    row = next(row for row in read(bundle / 'targets.json') if row['id'] == target)
    profile = read(bundle / 'profiles.json')[target]
    info = json.loads(fetch(f'https://raw.githubusercontent.com/SNodeC/Packages/{ref}/{profile["directory"]}/build.json')) if dependencies(os.environ['BUILD_PROJECT']) else {}
    info = info.get('targets', {}).get(row['arch'], info)
    activate(bundle, target, info, os.environ['BUILD_PROJECT'])
    if not ready(profile, {}, os.environ['BUILD_PROJECT'], info):
        raise ValueError('Missing published prerequisite')
    write(Path('published-snodec/build.json'), info)
    return None


def transaction(root, payload):
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'change.json'
        write(path, payload)
        run('bash', str(ROOT / 'ci/publish/status.sh'), str(root), 'control', str(path))
    return read(root / 'status.json')


def change(root, payload):
    from ci.publish.publication import migrate
    state = read(root / 'status.json', dict(repository='SNodeC/Packages', branch='main', counters={}, runs={}))
    migrate(state)
    if 'observation' in payload:
        state['observation'] = payload['observation']
    for project, request in payload.get('requests', {}).items():
        if state.get('requests', {}).get(project, {}).get('capture') == request['capture'] and request['capture'] not in state['runs']:
            state['requests'][project] = request
    for capture, key, node in payload.get('nodes', []):
        nodes = state['runs'][capture].setdefault('nodes', {})
        if nodes.get(key, {}).get('status') != 'published' or node['status'] == 'published':
            nodes[key] = node
    if payload.get('retry'):
        capture, project, target = payload['retry'].split('/')
        node = state['runs'][capture]['nodes'][target + '/' + project]
        if node.get('status') == 'published' or node.get('status') not in TERMINAL and not node.get('observation'):
            raise ValueError('Retry requires a terminal or unobservable task')
        if node.get('observation', {}).get('category') == 'expiry':
            node.pop('artifact', None)
        for field in ('publisher', 'publisher_intent', 'observation', 'reason', 'category'):
            node.pop(field, None)
        node.update(status='publishing' if node.get('artifact') else 'pending', waiting=False, builds=0, publications=0)
        if not node.get('artifact'):
            node.pop('source', None)
            node.pop('request', None)
    write(root / 'status.json', state)
    return None


def capacity():
    token = os.environ.get('OBSERVER_TOKEN')
    if not token:
        raise ValueError('A read-only organization observer credential is required')
    org = api('orgs/SNodeC', token=token)
    limit = CONFIG['settings']['capacity']
    if limit == 'plan':
        plan = org.get('plan', {}).get('name')
        if plan not in {'free', 'pro', 'team', 'enterprise'}:
            raise ValueError('Organization plan is unavailable; grant read access or configure capacity')
        limit = {'free': 20, 'pro': 40, 'team': 60, 'enterprise': 500}[plan]
    if limit <= CONFIG['settings']['headroom']:
        raise ValueError('Headroom must be below the observed capacity limit')
    repos, page, more = [], 1, True
    while more:
        batch = api(f'orgs/SNodeC/repos?type=all&per_page=100&page={page}', token=token)
        repos.extend(batch)
        more = len(batch) == 100
        page += 1
    if 'total_private_repos' not in org or len(repos) != org['public_repos'] + org['total_private_repos']:
        raise ValueError('Observer cannot see the complete organization inventory, including private repositories')
    occupied, backlog = {}, 0
    for repo in repos:
        active = {r['id']: r for status in ('queued', 'waiting', 'pending', 'requested', 'in_progress')
                  for r in listing(f'repos/SNodeC/{repo["name"]}/actions/runs?status={status}', 'workflow_runs', token=token)}
        for origin in active.values():
            jobs = listing(f'repos/SNodeC/{repo["name"]}/actions/runs/{origin["id"]}/attempts/{origin["run_attempt"]}/jobs', 'jobs', token=token)
            backlog += sum(j['status'] in {'queued', 'waiting', 'pending', 'requested'} for j in jobs)
            for job in jobs:
                if job['status'] == 'in_progress' and 'self-hosted' not in job.get('labels', []):
                    if not job.get('runner_id'):
                        raise ValueError('Running job has unknown runner allocation')
                    occupied[repo['name'], job['id']] = dict(run=origin['id'], name=job['name'], title=origin.get('display_title'))
    print(f'Capacity: {len(occupied)}/{limit} occupied hosted jobs; {backlog} observed waiting jobs (not occupied); headroom {CONFIG["settings"]["headroom"]}')
    return limit - len(occupied), occupied


def receive(request, bundle):
    if request.get('project') not in REPOSITORIES or request.get('status', 'publishing') not in {'running', 'publishing', 'failed', 'cancelled'}:
        raise ValueError('Unregistered callback repository or status')
    from ci.repository import unchanged
    unchanged(bundle)
    if read(bundle / 'context.json')['run_id'] != request['capture'] or request['project'] not in read(bundle / 'revisions.json'):
        raise ValueError('Callback capture or selected project mismatch')
    capture_run(request['capture'])
    state = json.loads(content('Packages', 'status.json', 'main'))
    key = request['target'] + '/' + request['project']
    if request['capture'] not in state['runs'] or key not in state['runs'][request['capture']].get('nodes', {}):
        raise ValueError('Unknown scheduled target')
    node = state['runs'][request['capture']]['nodes'][key]
    generation = state['runs'][request['capture']]
    if generation['context'] != read(bundle / 'context.json') or generation['profiles_hash'] != digest(bundle / 'profiles.json'):
        raise ValueError('Capture context or pinned definition snapshot changed')
    if not node.get('request'):
        raise ValueError('Callback target has no admitted build request')
    expected = node['request']
    if node.get('source') and (str(node['source']['run']) != str(request['run']) or int(request['attempt']) < node['source']['attempt']):
        raise ValueError('Callback belongs to another build execution')
    if any(expected.get(k) != request.get(k) for k in ('capture', 'project', 'target', 'publication', 'intent')):
        raise ValueError('Callback does not match the scheduled build')
    repo = 'SNodeC/' + request['project']
    origin = api(f'repos/{repo}/actions/runs/{identity(request["run"])}/attempts/{identity(request["attempt"])}')
    if (origin['event'] != 'workflow_dispatch' or origin['path'] != '.github/workflows/build-distribution-packages.yml'
            or origin['head_repository']['full_name'] != repo or origin['display_title'] != 'Packages · ' + request['intent']
            or origin['actor']['login'] != expected['actor']):
        raise ValueError('Callback workflow identity does not match admission')
    job = api(f'repos/{repo}/actions/jobs/{identity(request.get("job", ""))}')
    if str(job['run_id']) != str(request['run']) or str(job['run_attempt']) != str(request['attempt']) or job['name'] != 'build / ' + request['target']:
        raise ValueError('Callback job does not match the target and attempt')
    artifact = request.get('artifact')
    if request.get('status', 'publishing') == 'publishing' and not artifact:
        raise ValueError('A publication callback needs an artifact')
    if artifact:
        actual = api(f'repos/{repo}/actions/artifacts/{identity(artifact["id"])}')
        if actual['expired'] or actual.get('digest') != artifact['digest'] or actual['workflow_run']['id'] != int(request['run']) or actual['name'] != f'packages-{request["project"]}-{request["target"]}-{request["attempt"]}':
            raise ValueError('Artifact identity or bytes changed')
    activate(bundle, request['target'])
    row = next(row for row in read(bundle / 'targets.json') if row['id'] == request['target'])
    profile = read(bundle / 'profiles.json')[request['target']]
    baseline = json.loads(content('Packages', profile['directory'] + '/build.json', expected['publication'])) if dependencies(request['project']) else {}
    baseline = baseline.get('targets', {}).get(row['arch'], baseline)
    activate(bundle, request['target'], baseline, request['project'])
    receipt = dict(capture=request['capture'], source=dict(run=int(request['run']), attempt=int(request['attempt'])), artifact=artifact,
                   job=job['id'], job_url=job['html_url'], tooling=read(bundle / 'context.json')['recipe_commit'], publication=request['publication'])
    return dict(receipt=json.dumps(receipt), target=json.dumps(row), project=request['project'], run=request['run'], attempt=request['attempt'],
                artifact_id=artifact['id'] if artifact else '', run_url=job['html_url'], publication=request['publication'], baseline=json.dumps(baseline))


def artifact(request, destination):
    with tempfile.TemporaryFile() as archive:
        subprocess.run(['gh', 'api', f'repos/SNodeC/{request["project"]}/actions/artifacts/{identity(request["artifact"]["id"])}/zip'], stdout=archive, check=True, timeout=120)
        archive.seek(0)
        if 'sha256:' + hashlib.file_digest(archive, 'sha256').hexdigest() != request['artifact']['digest']:
            raise ValueError('Downloaded artifact digest mismatch')
        archive.seek(0)
        with zipfile.ZipFile(archive) as contents:
            if any(Path(item.filename).is_absolute() or '..' in Path(item.filename).parts or item.external_attr >> 16 & 0o170000 == 0o120000 for item in contents.infolist()):
                raise ValueError('Unsafe artifact path or symlink')
            contents.extractall(destination)
    return None


def report(bundle, status):
    request = json.loads(os.environ['PACKAGE_REQUEST'])
    request.update(run=os.environ['GITHUB_RUN_ID'], attempt=os.environ['GITHUB_RUN_ATTEMPT'], job=os.environ['BUILD_JOB_ID'], status=status)
    if status == 'publishing':
        items = listing(f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{request["run"]}/artifacts', 'artifacts')
        artifact = next(a for a in items if a['name'] == f'packages-{request["project"]}-{request["target"]}-{request["attempt"]}' and not a['expired'])
        request['artifact'] = dict(id=artifact['id'], digest=artifact['digest'])
    api(f'repos/{COORDINATOR}/actions/workflows/control-packages.yml/dispatches', dict(ref='main', inputs=dict(report=json.dumps(request))), token=os.environ['NOTIFY_TOKEN'])
    return None


def failure(error, previous=None):
    status = getattr(error, 'status', 0)
    category = ('transient' if 'rate limit' in str(error).lower() else 'expiry' if status in {404, 410}
                else 'configuration' if isinstance(error, (ValueError, KeyError, StopIteration, TypeError)) or status in {401, 403, 422}
                else 'transient')
    count = min(6, (previous or {}).get('failures', 0) + 1)
    delay = min(1800, max(1800 if category == 'configuration' else 60 * 2 ** (count - 1), getattr(error, 'retry_after', 0)))
    return dict(category=category, reason=('Malformed external facts: ' if isinstance(error, (KeyError, StopIteration, TypeError)) else '') + str(error),
                failures=count, retry_at=time.time() + delay)


def locate(repo, workflow, intent, created, actor):
    path = f'repos/{repo}/actions/workflows/{workflow}/runs?' + urlencode(dict(created='>=' + created))
    matches = [r for r in listing(path, 'workflow_runs') if r['display_title'] == intent and r['actor']['login'] == actor]
    if not matches and time.time() - datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp() > 1800:
        raise ApiError(410, 'Dispatch visibility unresolved after 30 minutes; inspect runs before operator retry')
    return min(matches, key=lambda r: r['id']) if matches else None


def observe(node, project, row):
    request = node.get('request')
    publisher = bool(node.get('publisher_intent'))
    terminal = node['status'] in TERMINAL
    if request:
        repo = COORDINATOR if publisher else 'SNodeC/' + project
        owner = node.get('publisher') if publisher else node.get('source', {}).get('run')
        if not owner:
            try:
                origin = locate(repo, 'sign-and-publish-packages.yml' if publisher else 'build-distribution-packages.yml',
                                'Publish · ' + node['publisher_intent'] if publisher else 'Packages · ' + request['intent'],
                                node.get('publish_created', request['created']) if publisher else request['created'], request['actor'])
            except ApiError as error:
                if error.status == 410 and str(error).startswith('Dispatch visibility unresolved'):
                    node['waiting'] = False
                raise
            if origin:
                owner = origin['id']
                node['publications' if publisher else 'builds'] = node.get('publications' if publisher else 'builds', 0) + 1
                node['publisher' if publisher else 'source'] = owner if publisher else dict(run=owner, attempt=origin['run_attempt'])
        if owner:
            origin = api(f'repos/{repo}/actions/runs/{owner}')
            attempt, job = origin['run_attempt'], None
            if not publisher and attempt > node['source']['attempt']:
                node['source']['attempt'] = attempt
                if not terminal:
                    for field in ('artifact', 'job', 'job_url'):
                        node.pop(field, None)
                    node['status'] = 'pending'
            if publisher or terminal or not node.get('artifact') or node.get('waiting'):
                if origin['status'] != 'completed' or not terminal and not publisher:
                    jobs = listing(f'repos/{repo}/actions/runs/{owner}/attempts/{attempt}/jobs', 'jobs')
                    name = 'write' if publisher else 'build / ' + row['id']
                    job = next((j for j in jobs if j['name'] == name and j['run_attempt'] == attempt), None)
                    if job and not publisher:
                        node.update(job=job['id'], job_url=job['html_url'], attempt=attempt)
                node['waiting'] = origin['status'] != 'completed' and not (
                    job and (job['status'] == 'completed' or job['status'] == 'in_progress' and job.get('runner_id')))
                if not terminal:
                    if publisher and origin['status'] == 'completed':
                        node.update(status='failed', category='deterministic', reason='Publication ended without a receipt; operator retry required')
                    elif not publisher and origin['status'] == 'completed':
                        artifacts = listing(f'repos/{repo}/actions/runs/{owner}/artifacts', 'artifacts')
                        artifact = next((a for a in artifacts if a['name'] == f'packages-{project}-{row["id"]}-{attempt}' and not a['expired']), None)
                        if artifact and job:
                            node.update(artifact=dict(id=artifact['id'], digest=artifact['digest']), status='publishing')
                        else:
                            if origin['conclusion'] == 'success' and node.get('observation', {}).get('failures', 0) < 3:
                                raise ApiError(0, 'Successful source completion has no artifact receipt yet; deferring observation')
                            node.update(status='cancelled' if origin['conclusion'] == 'cancelled' else 'failed',
                                        category='deterministic', reason='Build ended without a usable artifact')
                    elif not publisher and origin['status'] == 'in_progress':
                        node['status'] = 'running'
    return node


def tick(root, bundles):
    state = transaction(root, {})
    original = copy.deepcopy(state)
    observations, candidates, commitments = [], [], []
    for project, request in state.get('requests', {}).items():
        if request.get('eligible', True) and request['capture'] not in state['runs'] and time.time() >= request.get('observation', {}).get('retry_at', 0):
            try:
                if capture_run(request['capture'])['status'] == 'completed':
                    request.update(eligible=False, reason='Capture ended without a durable generation; inspect and retry capture or re-request')
                request.pop('observation', None)
            except (ApiError, ValueError, KeyError, StopIteration, TypeError, OSError, subprocess.SubprocessError) as error:
                request['observation'] = failure(error, request.get('observation'))
    state = transaction(root, dict(requests=state.get('requests', {})))
    publication = run('git', '-C', str(root), 'rev-parse', 'HEAD')
    reservations = {p: r for p, r in state.get('requests', {}).items() if r.get('eligible', True) and r['capture'] not in state['runs']}
    for generation in state['runs'].values():
        for key, node in generation.get('nodes', {}).items():
            terminal = node['status'] in TERMINAL
            if (node.get('request') and node['status'] != 'published' and (not terminal or node.get('waiting'))
                    and time.time() >= node.get('observation', {}).get('retry_at', 0)):
                observed = copy.deepcopy(node) if terminal else node
                try:
                    observe(observed, key.rsplit('/', 1)[1], next(r for r in generation['targets'] if key.startswith(r['id'] + '/')))
                    node.update({k: v for k, v in observed.items()
                                 if not terminal or k in {'source', 'publisher', 'job', 'job_url', 'attempt', 'waiting'}})
                    node.pop('observation', None)
                except (ApiError, ValueError, KeyError, StopIteration, TypeError, OSError, subprocess.SubprocessError) as error:
                    node['observation'] = failure(error, node.get('observation'))
                    if getattr(error, 'status', None) == 410 and str(error).startswith('Dispatch visibility unresolved'):
                        node['waiting'] = False
                    if not terminal and node['observation']['category'] == 'expiry':
                        node.update(status='failed', reason=str(error))
    for capture, generation in state['runs'].items():
        if generation['context'].get('contract') == 3:
            for row in generation['targets']:
                info, _ = published(root, row)
                for project in generation['revisions']:
                    key = row['id'] + '/' + project
                    node = copy.deepcopy(generation.get('nodes', {}).get(key, dict(status='pending', attempt=0)))
                    receipt = info.get('publications', {}).get(project, {})
                    if receipt.get('capture') == capture and receipt.get('revision') == generation['revisions'][project]:
                        node.update(status='published', job_url=receipt.get('job_url'), published_at=receipt.get('published_at'))
                    try:
                        changed = (not node.get('waiting') and node.get('dependencies') is not None and node.get('category') != 'excluded'
                                   and node['status'] != 'published' and time.time() >= node.get('observation', {}).get('retry_at', 0)
                                   and node['dependencies'] != binding(info, node.get('requires', [])))
                        if changed and not node.get('waiting') and (node.get('category') == 'blocked' or
                                node['status'] in {'failed', 'superseded'} and node.get('category') != 'excluded'):
                            node = (dict(status='pending', attempt=0, builds=0, publications=0, cause='dependent')
                                    if CONFIG['settings']['rebuild_overlap'] or node.get('category') == 'blocked' and
                                    not any(node.get(k) for k in ('request', 'builds', 'artifact')) else
                                    node | dict(status='superseded', category='excluded', reason='Prerequisite replaced; explicit re-request required'))
                        if node['status'] not in TERMINAL and time.time() >= node.get('observation', {}).get('retry_at', 0):
                            if capture not in bundles:
                                directory = Path(os.environ['RUNNER_TEMP']) / ('package-capture-' + capture)
                                if not (directory / 'context.json').exists():
                                    artifacts = listing(f'repos/{COORDINATOR}/actions/runs/{capture}/artifacts', 'artifacts')
                                    if not any(a['name'] == 'source-pair' and not a['expired'] for a in artifacts):
                                        raise ApiError(410, 'Capture unavailable; a new explicit release is required')
                                    with tempfile.TemporaryDirectory(dir=directory.parent) as temporary:
                                        run('gh', 'run', 'download', capture, '--repo', COORDINATOR, '-n', 'source-pair', '-D', temporary)
                                        os.rename(temporary, directory)
                                from ci.repository import unchanged
                                try:
                                    unchanged(directory)
                                except RuntimeError as error:
                                    raise ApiError(410, 'Capture integrity failure; a new explicit release is required: ' + str(error)) from error
                                bundles[capture] = directory
                            profile = read(bundles[capture] / 'profiles.json')[row['id']]
                            if node.get('artifact') and not node.get('publisher_intent') and api(f'repos/SNodeC/{project}/actions/artifacts/{node["artifact"]["id"]}')['expired']:
                                raise ApiError(410, f'repos/SNodeC/{project}/actions/artifacts/{node["artifact"]["id"]}: artifact expired; rebuilding source')
                            if project not in profile['projects'] or not supports(project, row, profile['projects']) or not profile['sources'].get(project):
                                node.update(status='skipped', category='excluded', reason=profile.get('errors', {}).get(project, 'No published source for this target'))
                            else:
                                projects = bind_projects(profile['projects'], info, project)
                                required = dependencies(project, projects)
                                replacements = {}
                                for p in required + (project,):
                                    if eligible := [g for g in state['runs'].values() if g['context'].get('contract') == 3
                                                and p in g['revisions'] and g['sources'].get(row['id'], {}).get(p)
                                                and (g['context']['release_project'] == p or
                                                     g['sources'][row['id']][p] == profile['sources'].get(p))
                                                and int(g['revisions'][p]) > int(generation['revisions'].get(p, 0))]:
                                        replacements[p] = max(eligible, key=lambda g: int(g['revisions'][p]))
                                expected = {p: str(max(int(generation['revisions'].get(p, 0)), int(replacements.get(p, {}).get('revisions', {}).get(p, 0)), int(reservations.get(p, {}).get('revision', 0)))) for p in required}
                                selected = profile | dict(sources=profile['sources'] | {p: g['sources'][row['id']][p] for p, g in replacements.items() if p in required})
                                node['requires'] = list(required)
                                if project in replacements or project_revision(info, project, ownership(info)) > int(generation['revisions'][project]):
                                    node.update(status='superseded', category='excluded', reason='A newer project release owns this target')
                                elif not CONFIG['settings']['rebuild_overlap'] and any(int(expected[p]) and project_revision(info, p, projects) > int(expected[p]) for p in required):
                                    node.update(status='superseded', category='excluded', reason='Prerequisite replaced; explicit re-request required')
                                elif missing := missing_prerequisites(project, row, info, generation['revisions'] | replacements, projects):
                                    node.update(status='unsatisfiable', category='blocked', dependencies=binding(info, required, projects), reason='Missing prerequisite target or publication: ' + ', '.join(missing))
                                elif not ready(selected, expected, project, info, projects):
                                    blocked = [d for d in required if replacements.get(d, generation).get('nodes', {}).get(row['id'] + '/' + d, {}).get('status') in {'failed', 'cancelled', 'skipped'}]
                                    if blocked:
                                        node.update(status='skipped', category='blocked', dependencies=binding(info, required, projects), reason='Prerequisite unavailable (failed, cancelled or not selected): ' + ', '.join(blocked))
                                else:
                                    if changed and CONFIG['settings']['rebuild_overlap'] and node['status'] == 'publishing':
                                        node = dict(status='pending', attempt=0, builds=0, publications=0, requires=list(required), cause='dependent')
                                    if node['status'] not in TERMINAL and not node.get('publisher_intent') and (node.get('artifact') or not node.get('request')) and int(reservations.get(project, {}).get('revision', 0)) <= int(generation['revisions'][project]):
                                        cause = node.get('cause', 'release' if project == generation['context']['release_project'] else 'dependent')
                                        if required and binding(profile['baseline'], required, projects) != binding(info, required, projects):
                                            cause = 'dependent'
                                        node['dependencies'] = binding(info, required, projects)
                                        candidates.append((0 if node.get('artifact') else 1 if cause == 'dependent' else 2,
                                                           generation['context']['captured_at'], capture, project, row, node,
                                                           ownership(info) | {p: projects[p] for p in required}, cause))
                            node.pop('observation', None)
                    except (ApiError, ValueError, KeyError, StopIteration, TypeError, OSError, subprocess.SubprocessError) as error:
                        node['observation'] = failure(error, node.get('observation'))
                        if node['status'] not in TERMINAL and node['observation']['category'] == 'expiry':
                            if node.get('artifact') and '/actions/artifacts/' in str(error):
                                for field in ('artifact', 'source', 'request', 'job', 'job_url'):
                                    node.pop(field, None)
                                node.update(status='pending', waiting=False)
                            else:
                                node.update(status='failed', reason=str(error))
                    if node.get('request') and node['status'] != 'published':
                        publisher = bool(node.get('publisher_intent'))
                        owner = node.get('publisher') if publisher else node.get('source', {}).get('run')
                        if node.get('waiting'):
                            commitments.append(('DistributionPackages' if publisher else project, owner, 'write' if publisher else 'build / ' + row['id'],
                                                'Publish · ' + node['publisher_intent'] if publisher else 'Packages · ' + node['request']['intent']))
                    generation.setdefault('nodes', {})[key] = node
                    observations.append((capture, key, node))
    state = transaction(root, dict(nodes=observations))
    observation = state.get('observation', {})
    if candidates and time.time() >= observation.get('retry_at', 0):
        try:
            free, occupied = capacity()
            transaction(root, dict(observation={}))
        except (ApiError, ValueError, KeyError, StopIteration, TypeError, OSError, subprocess.SubprocessError) as error:
            transaction(root, dict(observation=failure(error, observation)))
            print('::error::Capacity unknown; artifacts retained, no new work admitted: ' + str(error))
            free, occupied = 0, {}
        free -= sum(not any(repo == owner and job['name'] == name and (job['run'] == number if number else job['title'] == title) for (repo, _), job in occupied.items()) for owner, number, name, title in commitments)
        publishing = any(n.get('publisher_intent') and n['status'] not in TERMINAL for g in state['runs'].values() for n in g.get('nodes', {}).values())
        headroom = max(0, CONFIG['settings']['headroom'] - sum(repo == 'DistributionPackages' and str(job['run']) == os.environ.get('GITHUB_RUN_ID') for (repo, _), job in occupied.items()))
        blocked = False
        for priority, _, capture, project, row, node, definitions, cause in sorted(candidates, key=lambda c: c[:4]):
            kind = 'publish' if priority == 0 else 'build'
            blocked = blocked or kind == 'publish' and publishing
            if not blocked and free > (0 if kind == 'publish' else headroom):
                budget = 'publications' if kind == 'publish' else 'builds'
                if node.get(budget, 0) < 3:
                    if kind == 'build':
                        node['request'] = dict(capture=capture, project=project, target=row['id'], runner=row['runner'], publication=publication,
                                               intent=uuid.uuid4().hex, actor=os.environ['COORDINATOR_ACTOR'], created=datetime.now(timezone.utc).isoformat())
                        node.update(cause=cause, waiting=True)
                    request = dict(node['request'])
                    if kind == 'build':
                        request['definitions'] = definitions
                    else:
                        node.update(waiting=True, publisher_intent=uuid.uuid4().hex, publish_created=datetime.now(timezone.utc).isoformat())
                        request.update(publish_intent=node['publisher_intent'], run=node['source']['run'], attempt=node['source']['attempt'], job=node['job'], artifact=node['artifact'])
                    transaction(root, dict(nodes=[(capture, row['id'] + '/' + project, node)]))
                    repo = COORDINATOR if kind == 'publish' else 'SNodeC/' + project
                    workflow = 'sign-and-publish-packages.yml' if kind == 'publish' else 'build-distribution-packages.yml'
                    try:
                        ref = api('repos/' + repo)['default_branch']
                        result = api(f'repos/{repo}/actions/workflows/{workflow}/dispatches', dict(ref=ref, inputs=dict(request=json.dumps(request)), return_run_details=True))
                        if result and result.get('workflow_run_id'):
                            node[budget] = node.get(budget, 0) + 1
                            node['publisher' if kind == 'publish' else 'source'] = result['workflow_run_id'] if kind == 'publish' else dict(run=result['workflow_run_id'], attempt=1)
                    except (ApiError, OSError, subprocess.SubprocessError) as error:
                        node['observation'] = failure(error)
                        if isinstance(error, ApiError) and 400 <= error.status < 500 and error.status not in {408, 429} and 'rate limit' not in str(error):
                            node.pop('publisher_intent' if kind == 'publish' else 'request', None)
                            node.update(status='failed', waiting=False, reason='Dispatch rejected: ' + str(error))
                    publishing = publishing or kind == 'publish' and bool(node.get('publisher_intent'))
                    free -= 1
                else:
                    node.update(status='failed', reason=budget + ' dispatch budget exhausted; operator retry required')
                transaction(root, dict(nodes=[(capture, row['id'] + '/' + project, node)]))
    return original != read(root / 'status.json') or any(n['status'] not in TERMINAL for g in state['runs'].values() if g['context'].get('contract') == 3 for n in g.get('nodes', {}).values())


def apply_report(root, request, bundle):
    result = receive(request, bundle)
    state = transaction(root, {})
    key = request['target'] + '/' + request['project']
    node = state['runs'][request['capture']]['nodes'][key]
    later = int(request['attempt']) > node.get('source', {}).get('attempt', 0)
    if node['status'] not in TERMINAL or node['status'] != 'published' and (later or request.get('artifact') and not node.get('artifact')):
        if later:
            node.pop('artifact', None)
            node.pop('publisher', None)
            node.pop('publisher_intent', None)
        receipt = json.loads(result['receipt'])
        artifact = request.get('artifact') or node.get('artifact')
        node.update(source=receipt['source'], job=receipt['job'], job_url=receipt['job_url'], artifact=artifact,
                    status='publishing' if artifact else 'pending')
        transaction(root, dict(nodes=[(request['capture'], key, node)]))
    return None


def authorize_operator():
    actor = os.environ.get('GITHUB_TRIGGERING_ACTOR', os.environ['GITHUB_ACTOR'])
    if actor.endswith('[bot]') or api(f'repos/{COORDINATOR}/collaborators/{actor}/permission')['permission'] not in {'admin', 'write'}:
        raise ValueError('Operator action requires a human with write access to DistributionPackages')
    return None


def main():
    command, *args = sys.argv[1:]
    values = {}
    if command == 'notify':
        if not re.fullmatch(TAG, os.environ['GITHUB_REF_NAME']):
            raise ValueError('Only semantic version tags notify the coordinator')
        api(f'repos/{COORDINATOR}/actions/workflows/orchestrate-packages.yml/dispatches', dict(ref='main', inputs=dict(
            project=os.environ['GITHUB_REPOSITORY'].split('/')[1], tag=os.environ['GITHUB_REF_NAME'], sha=os.environ['GITHUB_SHA'], run=os.environ['GITHUB_RUN_ID'],
            definition=Path('source/ci/packages.json').read_text())))
    elif command == 'operator':
        authorize_operator()
    elif command == 'intake':
        values = intake(json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())['inputs'])
    elif command == 'retry-capture':
        retry_capture()
    elif command == 'baseline':
        baseline(Path(args[0]), *args[1:])
    elif command == 'authorize':
        request = json.loads(os.environ['PACKAGE_REQUEST'])
        capture_run(request['capture'])
        from ci.repository import unchanged
        unchanged(Path(args[0]))
        activate(Path(args[0]), request['target'])
        row = next(r for r in read(Path(args[0]) / 'targets.json') if r['id'] == request['target'])
        if request['project'] != os.environ['BUILD_PROJECT'] or request['runner'] != row['runner']:
            raise ValueError('Build request target or repository mismatch')
        values = dict(row=json.dumps(row))
    elif command == 'artifact':
        artifact(json.loads(os.environ['PACKAGE_REQUEST']), Path(args[0]))
    elif command == 'report':
        report(Path(args[0]), args[1])
    elif command == 'receive':
        values = receive(json.loads(os.environ['PACKAGE_REQUEST']), Path(args[0]))
    elif command == 'control':
        root, bundles = Path(args[0]), {}
        operator = os.environ.get('PACKAGE_RETRY') or os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and not os.environ.get('PACKAGE_REPORT')
        if operator:
            authorize_operator()
            if not os.environ.get('PACKAGE_REPORT'):
                transaction(root, dict(observation={}))
            if os.environ.get('PACKAGE_RETRY'):
                transaction(root, dict(retry=os.environ['PACKAGE_RETRY']))
        if os.environ.get('PACKAGE_REPORT'):
            request = json.loads(os.environ['PACKAGE_REPORT'])
            directory = Path(os.environ['RUNNER_TEMP']) / 'callback'
            run('gh', 'run', 'download', identity(request['capture']), '--repo', COORDINATOR, '-n', 'source-pair', '-D', str(directory))
            apply_report(root, request, directory)
        if tick(root, bundles) and any(g.get('context', {}).get('contract') == 3 for g in read(root / 'status.json')['runs'].values()):
            run('bash', str(ROOT / 'ci/publish/status.sh'), str(root), 'project')
    else:
        raise ValueError('Unknown coordinator command')
    if values:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            for key, value in values.items():
                print(f'{key}={value}', file=output)
    return None


if __name__ == '__main__':
    main()
