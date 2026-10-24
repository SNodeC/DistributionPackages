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
from ci.repository import (ownership, COORDINATOR, OWNER, COORDINATOR_NAME, FEED, FEED_BRANCH, TAG, version,
                           source_tag, release_view, generation_tag, dependent_source, validate_projects, affected, prepare,
                           work_index, cascade_blockers, requested_projects, unchanged)
from ci.publish.publication import read, write, published, TERMINAL

SHA = r'[0-9a-f]{40}'


def api(path, payload=None, token=None):
    token = token or (os.environ.get('PACKAGES_TOKEN') if path.startswith(f'repos/{FEED}/') else None)
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
    parent = payload if payload.get('kind') == 'capture' else {}
    state = read(Path('published/status.json'), {})
    if parent:
        if os.environ.get('GITHUB_TRIGGERING_ACTOR', os.environ['GITHUB_ACTOR']) != os.environ['COORDINATOR_ACTOR']:
            authorize_operator()
        project = payload['project']
        node = state['runs'][identity(payload['capture'])]['nodes'][payload['target'] + '/' + project]
        if os.environ['GITHUB_ACTOR'] != os.environ['COORDINATOR_ACTOR'] or node.get('request') != payload:
            raise ValueError('Cascade capture requires the admitted coordinator intent')
        if not state.get('requests', {}).get(project):
            raise ValueError('Cascade cannot activate an inactive repository')
        config = dependent_source(project, state['requests'])
        payload = dict(project=project, tag=config['_tag'], sha=config['_commit'], run='0',
                       definition=json.dumps({k: v for k, v in config.items() if not k.startswith('_')}))
    project, tag, sha = payload['project'], payload['tag'], payload['sha']
    if project not in REPOSITORIES or not re.fullmatch(TAG, tag) or not re.fullmatch(SHA, sha):
        raise ValueError('Release needs a registered project, version tag and exact commit')
    previous = state.get('requests', {}).get(project, {}).get(tag, {})
    requested_at, duplicate = '', False
    if not parent:
        origin = api(f'repos/{OWNER}/{project}/actions/runs/{identity(payload["run"])}')
        if (origin['event'] != 'push' or origin['path'] != '.github/workflows/build-distribution-packages.yml'
                or origin['head_repository']['full_name'] != f'{OWNER}/{project}'
                or origin['head_branch'] != tag or origin['head_sha'] != sha):
            raise ValueError('Release notification does not match the upstream tag workflow')
        requested_at = origin['created_at']
        duplicate = str(previous.get('run', '')) == str(payload['run']) and previous.get('capture') != os.environ.get('GITHUB_RUN_ID')
        duplicate = duplicate or (previous.get('at', ''), int(previous.get('run', 0))) > (requested_at, int(payload['run']))
    if content(project, 'VERSION', sha).decode().strip() != tag[1:]:
        raise ValueError('Release tag and VERSION disagree')
    configure(Path('published'), project, sha, json.loads(payload['definition']))
    return dict(project=project, tag=tag, sha=sha, duplicate=str(duplicate).lower(), requested_at=requested_at,
                run=payload['run'], parent=json.dumps(parent), target=parent.get('target', ''), cause='dependent' if parent else 'release')


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


def baseline(bundle, target, ref):
    from ci.repository import fetch
    activate(bundle, target)
    if not re.fullmatch(SHA, ref):
        raise ValueError('Dependencies require an exact publication commit')
    row = next(row for row in read(bundle / 'targets.json') if row['id'] == target)
    profile = read(bundle / 'profiles.json')[target]
    info = (json.loads(fetch(f'https://raw.githubusercontent.com/{FEED}/{ref}/{profile["directory"]}/build.json'))
            if dependencies(os.environ['BUILD_PROJECT']) else {})
    info = info.get('targets', {}).get(row['arch'], info)
    activate(bundle, target, info, os.environ['BUILD_PROJECT'])
    if missing_prerequisites(os.environ['BUILD_PROJECT'], info, {}, PROJECTS):
        raise ValueError('Missing published prerequisite')
    write(Path('published-baseline/build.json'), info)
    return None


def transaction(root, payload):
    payload = dict(payload)
    if payload.get('nodes') or payload.get('requests'):
        base = payload.pop('base')
        payload['nodes'] = [(capture, key, node, base['runs'][capture].get('nodes', {}).get(key))
                            for capture, key, node in payload.get('nodes', [])]
        payload['requests'] = {p: {tag: [request, base.get('requests', {}).get(p, {}).get(tag)] for tag, request in values.items()}
                               for p, values in payload.get('requests', {}).items()}
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'change.json'
        write(path, payload)
        run('bash', str(ROOT / 'ci/publish/status.sh'), str(root), 'control', str(path))
    return read(root / 'status.json')


def change(root, payload):
    state = read(root / 'status.json', dict(repository=FEED, branch=FEED_BRANCH, counters={}, runs={}))
    if 'observation' in payload:
        state['observation'] = payload['observation']
    for project, requests in payload.get('requests', {}).items():
        for tag, (request, base) in requests.items():
            if state.get('requests', {}).get(project, {}).get(tag) == base:
                state['requests'][project][tag] = request
    updates = {(capture, key): (node, base) for capture, key, node, base in payload.get('nodes', [])}
    for (capture, key), (node, base) in updates.items():
        nodes = state['runs'][capture].setdefault('nodes', {})
        if nodes.get(key) == base:
            nodes[key] = node
    for capture, key, admitted, number in payload.get('acknowledgements', []):
        node = state['runs'][capture].get('nodes', {}).get(key, {})
        publisher = admitted.get('publisher_intent')
        budget, field = ('publications', 'publisher') if publisher else ('builds', 'source')
        owner = node.get('publisher') if publisher else node.get('source', {}).get('run')
        # An early reservation has already authenticated and bound this capture intent.
        number = number or (owner if admitted['request'].get('kind') == 'capture' else None)
        if (number and node.get('request') == admitted['request'] and node.get('publisher_intent') == publisher
                and owner in {None, number}):
            node[budget] = max(node.get(budget, 0), admitted.get(budget, 0) + 1)
            if owner is None:
                node[field] = number if publisher else dict(run=number, attempt=1)
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
            for field in ('source', 'request', 'job', 'job_url'):
                node.pop(field, None)
    write(root / 'status.json', state)
    return None


def capacity():
    token = os.environ.get('OBSERVER_TOKEN')
    if not token:
        raise ValueError('A read-only organization observer credential is required')
    org = api(f'orgs/{OWNER}', token=token)
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
        batch = api(f'orgs/{OWNER}/repos?type=all&per_page=100&page={page}', token=token)
        repos.extend(batch)
        more = len(batch) == 100
        page += 1
    if 'total_private_repos' in org and len(repos) != org['public_repos'] + org['total_private_repos']:
        raise ValueError('Observer cannot see the complete organization inventory, including private repositories: '
                         f'listed={len(repos)}, public_repos={org.get("public_repos")}, '
                         f'total_private_repos={org.get("total_private_repos")}, owned_private_repos={org.get("owned_private_repos")}; '
                         'verify organization metadata and token repository scope')
    occupied, backlog = {}, 0
    for repo in repos:
        active = {r['id']: r for status in ('queued', 'waiting', 'pending', 'requested', 'in_progress')
                  for r in listing(f'repos/{OWNER}/{repo["name"]}/actions/runs?status={status}', 'workflow_runs', token=token)}
        for origin in active.values():
            jobs = listing(f'repos/{OWNER}/{repo["name"]}/actions/runs/{origin["id"]}/attempts/{origin["run_attempt"]}/jobs', 'jobs', token=token)
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
    unchanged(bundle)
    if read(bundle / 'context.json')['run_id'] != request['capture'] or request['project'] not in read(bundle / 'revisions.json'):
        raise ValueError('Callback capture or selected project mismatch')
    capture_run(request['capture'])
    state = json.loads(content(CONFIG['feed']['repository'], 'status.json', FEED_BRANCH))
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
    repo = OWNER + '/' + request['project']
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
    baseline = (json.loads(content(CONFIG['feed']['repository'], profile['directory'] + '/build.json', expected['publication']))
                if dependencies(request['project']) else {})
    baseline = baseline.get('targets', {}).get(row['arch'], baseline)
    activate(bundle, request['target'], baseline, request['project'])
    receipt = dict(capture=request['capture'], source=dict(run=int(request['run']), attempt=int(request['attempt'])), artifact=artifact,
                   job=job['id'], job_url=job['html_url'], tooling=read(bundle / 'context.json')['recipe_commit'], publication=request['publication'])
    return dict(receipt=json.dumps(receipt), target=json.dumps(row), project=request['project'], run=request['run'], attempt=request['attempt'],
                artifact_id=artifact['id'] if artifact else '', run_url=job['html_url'], publication=request['publication'], baseline=json.dumps(baseline))


def artifact(request, destination):
    with tempfile.TemporaryFile() as archive:
        subprocess.run(['gh', 'api', f'repos/{OWNER}/{request["project"]}/actions/artifacts/{identity(request["artifact"]["id"])}/zip'],
                       stdout=archive, check=True, timeout=120)
        archive.seek(0)
        if 'sha256:' + hashlib.file_digest(archive, 'sha256').hexdigest() != request['artifact']['digest']:
            raise ValueError('Downloaded artifact digest mismatch')
        archive.seek(0)
        try:
            contents = zipfile.ZipFile(archive)
        except zipfile.BadZipFile as error:
            raise ValueError('Malformed artifact ZIP') from error
        with contents:
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
    ref = api('repos/' + COORDINATOR, token=os.environ['NOTIFY_TOKEN'])['default_branch']
    api(f'repos/{COORDINATOR}/actions/workflows/control-packages.yml/dispatches',
        dict(ref=ref, inputs=dict(report=json.dumps(request))), token=os.environ['NOTIFY_TOKEN'])
    return None


def failure(error, previous=None):
    status = getattr(error, 'status', 0)
    category = ('transient' if 'rate limit' in str(error).lower() or isinstance(error, ApiError) and (status in {0, 408, 429} or status >= 500)
                else 'expiry' if status in {404, 410}
                else 'configuration' if isinstance(error, (ValueError, KeyError, StopIteration, TypeError, RuntimeError)) or status in {401, 403, 422}
                else 'transient')
    count = min(6, (previous or {}).get('failures', 0) + 1)
    delay = min(1800, max(1800 if category == 'configuration' else 60 * 2 ** (count - 1), getattr(error, 'retry_after', 0)))
    return dict(category=category, reason=('Malformed external facts: ' if isinstance(error, (KeyError, StopIteration, TypeError)) else '') + str(error),
                failures=count, retry_at=time.time() + delay)


def capture_failure(error):
    if os.environ.get('GITHUB_REPOSITORY') == COORDINATOR and os.environ.get('GITHUB_EVENT_PATH'):
        request = json.loads(json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text()).get('inputs', {}).get('request', '{}'))
        if request.get('kind') == 'capture':
            write(Path(os.environ['RUNNER_TEMP']) / 'capture-result.json', dict(intent=request['intent'],
                run=int(os.environ['GITHUB_RUN_ID']), attempt=int(os.environ['GITHUB_RUN_ATTEMPT']), failure=failure(error)))
    return None


def locate(repo, workflow, intent, created, actor):
    path = f'repos/{repo}/actions/workflows/{workflow}/runs?' + urlencode(dict(created='>=' + created))
    matches = [r for r in listing(path, 'workflow_runs') if r['display_title'] == intent and r['actor']['login'] == actor]
    if not matches and time.time() - datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp() > 1800:
        raise ApiError(410, 'Dispatch visibility unresolved after 30 minutes; inspect runs before operator retry')
    return min(matches, key=lambda r: r['id']) if matches else None


def observe(node, project, row):
    request = node.get('request')
    publisher = bool(node.get('publisher_intent'))
    capturing = request and request.get('kind') == 'capture'
    terminal = node['status'] in TERMINAL
    if request:
        repo = COORDINATOR if publisher or capturing else OWNER + '/' + project
        owner = node.get('publisher') if publisher else node.get('source', {}).get('run')
        if not owner:
            try:
                origin = locate(repo, ('sign-and-publish-packages.yml' if publisher else
                                       'orchestrate-packages.yml' if capturing else 'build-distribution-packages.yml'),
                                'Publish · ' + node['publisher_intent'] if publisher else ('Capture · ' if capturing else 'Packages · ') + request['intent'],
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
            origin = capture_run(owner) if capturing else api(f'repos/{repo}/actions/runs/{owner}')
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
                    name = 'write' if publisher else 'capture' if capturing else 'build / ' + row['id']
                    job = next((j for j in jobs if j['name'] == name and j['run_attempt'] == attempt), None)
                    if job and not publisher:
                        node.update(job=job['id'], job_url=job['html_url'], attempt=attempt)
                node['waiting'] = origin['status'] != 'completed' and not (
                    job and (job['status'] == 'completed' or job['status'] == 'in_progress' and job.get('runner_id')))
                if not terminal:
                    if publisher and origin['status'] == 'completed':
                        node.update(status='failed', category='deterministic', reason='Publication ended without a receipt; operator retry required')
                    elif capturing and origin['status'] == 'completed':
                        node.update(status='superseded' if origin['conclusion'] == 'success' else 'pending',
                                    reason='Capture finished; child generation owns the build')
                        if origin['conclusion'] != 'success':
                            if origin['actor']['login'] != request['actor'] or origin['display_title'] != 'Capture · ' + request['intent']:
                                raise ValueError('Capture failure origin does not match admission')
                            results = listing(f'repos/{repo}/actions/runs/{owner}/artifacts', 'artifacts')
                            result = next((a for a in results if a['name'] == f'capture-result-{attempt}' and not a['expired']), None)
                            if not result or result['workflow_run']['id'] != owner:
                                raise ValueError('Capture failed without its verified result; inspect capture logs and retry')
                            with tempfile.TemporaryDirectory() as directory:
                                artifact(dict(project=COORDINATOR_NAME, artifact=result), Path(directory))
                                result = read(Path(directory) / 'capture-result.json')
                            if (result['intent'] != request['intent'] or result['run'] != owner or result['attempt'] != attempt
                                    or result['failure']['category'] not in {'transient', 'configuration', 'expiry'}):
                                raise ValueError('Capture failure result does not match its intent and attempt')
                            node.update(status='failed', category=result['failure']['category'], reason=result['failure']['reason'])
                            if result['failure']['category'] == 'transient':
                                node.update(status='pending', observation=result['failure'])
                                node['observation']['retry_at'] = min(time.time() + 1800, max(time.time() + 60, result['failure']['retry_at']))
                                for field in ('request', 'source'):
                                    node.pop(field, None)
                    elif not publisher and origin['status'] == 'completed':
                        artifacts = listing(f'repos/{repo}/actions/runs/{owner}/artifacts', 'artifacts')
                        built = next((a for a in artifacts if a['name'] == f'packages-{project}-{row["id"]}-{attempt}' and not a['expired']), None)
                        if built and job:
                            node.update(artifact=dict(id=built['id'], digest=built['digest']), status='publishing')
                        else:
                            if origin['conclusion'] == 'success' and node.get('observation', {}).get('failures', 0) < 3:
                                raise ApiError(0, 'Successful source completion has no artifact receipt yet; deferring observation')
                            node.update(status='cancelled' if origin['conclusion'] == 'cancelled' else 'failed',
                                        category='deterministic', reason='Build ended without a usable artifact')
                    elif not publisher and origin['status'] == 'in_progress':
                        node['status'] = 'running'
    return node


def coverage(state, index, reservations, info, target, project, holder):
    work, captures = index
    latest = max(((version(t), v, c) for (x, p, t), (v, c, _) in work.items()
                  if (x, p) == (target, project)), default=((), 0, None))
    current = state['runs'].get(latest[2], {}).get('nodes', {}).get(target + '/' + project, {})
    related = [n for (c, k), n in captures.items() if k == target + '/' + project and c != holder]
    pending = bool(current and current['status'] not in TERMINAL) or any(
        p == project and version(t) >= latest[0] and supports(project, {'id': target}, {project: r['definition']})
        for (p, t), r in reservations.items()) or any(n['status'] not in TERMINAL for n in related)
    settled = any(n.get('dependencies') is not None and n['dependencies'] == binding(info, n.get('requires', []))
                  for n in [current, *related] if n.get('status') in TERMINAL - {'superseded'})
    return pending, settled


def capture_bundle(capture, bundles):
    if capture not in bundles:
        directory = Path(os.environ['RUNNER_TEMP']) / ('package-capture-' + capture)
        if not (directory / 'context.json').exists():
            artifacts = listing(f'repos/{COORDINATOR}/actions/runs/{capture}/artifacts', 'artifacts')
            if not any(a['name'] == 'source-pair' and not a['expired'] for a in artifacts):
                raise ApiError(410, 'Capture unavailable; a new explicit release is required')
            with tempfile.TemporaryDirectory(dir=directory.parent) as temporary:
                run('gh', 'run', 'download', capture, '--repo', COORDINATOR, '-n', 'source-pair', '-D', temporary)
                os.rename(temporary, directory)
        try:
            unchanged(directory)
        except RuntimeError as error:
            raise ApiError(410, 'Capture integrity failure; a new explicit release is required: ' + str(error)) from error
        bundles[capture] = directory
    return bundles[capture]


def tick(root, bundles):
    state = transaction(root, {})
    original = copy.deepcopy(state)
    observations, candidates, commitments = [], [], []
    for requests in state.get('requests', {}).values():
        for request in requests.values():
            if (request.get('eligible', True) and request['capture'] not in state['runs']
                    and time.time() >= request.get('observation', {}).get('retry_at', 0)):
                try:
                    if capture_run(request['capture'])['status'] == 'completed':
                        request.update(eligible=False, reason='Capture failed; inspect and retry capture or re-request')
                    request.pop('observation', None)
                except (ApiError, ValueError, KeyError, StopIteration, TypeError, OSError, subprocess.SubprocessError) as error:
                    request['observation'] = failure(error, request.get('observation'))
    state = transaction(root, dict(requests=state.get('requests', {}), base=original))
    base = copy.deepcopy(state)
    publication = run('git', '-C', str(root), 'rev-parse', 'HEAD')
    reservations = {(p, tag): r for p, requests in state.get('requests', {}).items() for tag, r in requests.items()
                    if r.get('eligible', True) and r['capture'] not in state['runs']}
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
                    if node.get('observation', {}).get('retry_at', 0) <= time.time():
                        node.pop('observation', None)
                except (ApiError, ValueError, KeyError, StopIteration, TypeError, OSError, subprocess.SubprocessError) as error:
                    node['observation'] = failure(error, node.get('observation'))
                    if getattr(error, 'status', None) == 410 and str(error).startswith('Dispatch visibility unresolved'):
                        node['waiting'] = False
                    if not terminal and (node['observation']['category'] == 'expiry' or
                            node['request'].get('kind') == 'capture' and not node.get('waiting') and node['observation']['category'] == 'configuration'):
                        node.update(status='failed', reason=str(error))
                observations.append((generation['run_id'], key, node))
    index = work, captures = work_index(state)
    for capture, generation in state['runs'].items():
        for row in generation['targets']:
            info, _ = published(root, row)
            for project, revision in generation['revisions'].items():
                key = row['id'] + '/' + project
                node = copy.deepcopy(generation.get('nodes', {}).get(key, dict(status='pending', attempt=0)))
                tag = generation_tag(generation, project, row['id'])
                own = release_view(info, project, tag)
                receipt = own.get('publications', {}).get(project, {})
                if receipt.get('capture') == capture and str(receipt.get('revision')) == str(revision):
                    node.update(status='published', job_url=receipt.get('job_url'), published_at=receipt.get('published_at'))
                try:
                    changed = (not node.get('waiting') and node.get('dependencies') is not None
                               and node.get('category') != 'excluded' and node['status'] != 'published'
                               and node['dependencies'] != binding(info, node.get('requires', [])))
                    if changed and node.get('request') and node['status'] == 'superseded':
                        node = (dict(status='pending', attempt=0, builds=0, publications=0, cause='dependent')
                                if CONFIG['settings']['rebuild_overlap'] else
                                node | dict(status='superseded', category='excluded',
                                            reason='Prerequisite replaced; pinned rebuild disabled by rebuild_overlap'))
                    if node['status'] not in TERMINAL and time.time() >= node.get('observation', {}).get('retry_at', 0):
                        profile = read(capture_bundle(capture, bundles) / 'profiles.json')[row['id']]
                        if (node.get('artifact') and not node.get('publisher_intent')
                                and api(f'repos/{OWNER}/{project}/actions/artifacts/{node["artifact"]["id"]}')['expired']):
                            raise ApiError(410, f'repos/{OWNER}/{project}/actions/artifacts/{node["artifact"]["id"]}: artifact expired; rebuilding source')
                        if project not in profile['projects'] or not supports(project, row, profile['projects']) or not profile['sources'].get(project):
                            node.update(status='skipped', category='excluded', reason=profile.get('errors', {}).get(project, 'No selected source for target'))
                        else:
                            projects = bind_projects(profile['projects'], info, project)
                            required = dependencies(project, projects)
                            newer = max(work.get((row['id'], project, tag), (0,))[0], project_revision(own, project))
                            reservation = reservations.get((project, tag), {})
                            node['requires'] = list(required)
                            if newer > int(revision):
                                node.update(status='superseded', category='excluded', reason='A newer revision of this version owns the target')
                            elif reservation and supports(project, row, {project: reservation['definition']}):
                                pass
                            elif (any(k == key and n['status'] not in TERMINAL and n.get('request')
                                      and str(n.get('source', {}).get('run')) not in state['runs'] for (_, k), n in captures.items())
                                    and tag == max((t for (x, p, t) in work if (x, p) == (row['id'], project)), key=version)):
                                pass
                            elif missing := missing_prerequisites(project, info, {}, projects):
                                node.update(status='unsatisfiable', category='blocked', dependencies=binding(info, required),
                                            reason='Missing prerequisite target or publication: ' + ', '.join(missing))
                            else:
                                if changed and node.get('artifact') and CONFIG['settings']['rebuild_overlap'] and not node.get('publisher_intent'):
                                    node = dict(status='pending', attempt=0, builds=0, publications=0, requires=list(required), cause='dependent')
                                if (node.get('cause', generation['context'].get('cause')) == 'dependent'
                                        and (blocked := cascade_blockers(info, required, state, row['id'], index))):
                                    node['reason'] = 'Awaiting prerequisite arms: ' + ', '.join(blocked)
                                    if node.get('artifact') and not node.get('publisher_intent'):
                                        node['status'] = 'pending'
                                    if any(status in TERMINAL for status, _ in blocked.values()):
                                        node.update(status='unsatisfiable', category='blocked', dependencies=binding(info, required),
                                                    reason='Prerequisite failed; retry the named arm: ' + ', '.join(blocked))
                                elif not node.get('publisher_intent') and (node.get('artifact') or not node.get('request')):
                                    node.pop('reason', None)
                                    cause = node.get('cause', generation['context'].get('cause',
                                        'release' if project == generation['context']['release_project'] else 'dependent'))
                                    node['dependencies'] = binding(info, required)
                                    candidates.append((0 if node.get('artifact') else 1 if cause == 'dependent' else 2,
                                        generation['context']['captured_at'], capture, project, row, node,
                                        ownership(info) | {p: projects[p] for p in required}, cause, 'build'))
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
                generation.setdefault('nodes', {})[key] = node
                observations.append((capture, key, node))
    graph = requested_projects(state.get('requests', {}))
    graph = validate_projects(graph) if graph else {}
    roots = []
    for capture, generation in state['runs'].items():
        if generation['context'].get('cascade', capture) == capture:
            changed_project = generation['context']['release_project']
            cascade = set(affected(changed_project, graph)) if changed_project in graph else set()
            for row in generation['targets']:
                info, _ = published(root, row)
                current = release_view(info, changed_project).get('publications', {}).get(changed_project, {}).get('capture') == capture
                roots.append((capture, generation, row, info, cascade, current))
                for key, held in list(generation.get('nodes', {}).items()):
                    project = key.rsplit('/', 1)[1]
                    if (key == row['id'] + '/' + project and project not in generation['revisions']
                            and held['status'] not in TERMINAL and not held.get('request')):
                        node = copy.deepcopy(held)
                        try:
                            reason = ('Root no longer current; the current root re-evaluates this dependent' if not current else
                                      'Dependent no longer selected on this row' if project not in cascade
                                      or not supports(project, row, graph) else
                                      'Already satisfied at this baseline' if coverage(
                                          state, index, reservations, info, row['id'], project, capture)[1] else '')
                            if reason:
                                node.update(status='superseded', reason=reason)
                                generation['nodes'][key] = node
                                captures[capture, key] = node
                                observations.append((capture, key, node))
                        except (ApiError, ValueError, KeyError, StopIteration, TypeError, OSError, subprocess.SubprocessError) as error:
                            node['observation'] = failure(error, node.get('observation'))
                            observations.append((capture, key, node))
    for capture, generation, row, info, cascade, current in roots:
        if current:
            for project in cascade - {generation['context']['release_project']}:
                key = row['id'] + '/' + project
                node = copy.deepcopy(generation.get('nodes', {}).get(key, dict(status='pending', attempt=0)))
                try:
                    projects = bind_projects(graph, info, project)
                    required = dependencies(project, projects)
                    pending, settled = coverage(state, index, reservations, info, row['id'], project, capture)
                    if (supports(project, row, projects) and not pending and not settled
                            and not cascade_blockers(info, required, state, row['id'], index)
                            and not node.get('request') and node['status'] not in TERMINAL
                            and time.time() >= node.get('observation', {}).get('retry_at', 0)):
                        node.update(requires=list(required), dependencies=binding(info, required))
                        captures[capture, key] = node
                        candidates.append((1, generation['context']['captured_at'], capture, project, row, node, {}, 'dependent', 'capture'))
                except (ApiError, ValueError, KeyError, StopIteration, TypeError, OSError, subprocess.SubprocessError) as error:
                    node['observation'] = failure(error, node.get('observation'))
                    observations.append((capture, key, node))
    for capture, generation in state['runs'].items():
        for key, node in generation.get('nodes', {}).items():
            if node.get('request') and node['status'] != 'published' and node.get('waiting'):
                publisher = bool(node.get('publisher_intent'))
                capturing = node['request'].get('kind') == 'capture'
                commitments.append((COORDINATOR_NAME if publisher or capturing else key.rsplit('/', 1)[1],
                    node.get('publisher') if publisher else node.get('source', {}).get('run'),
                    'write' if publisher else 'capture' if capturing else 'build / ' + key.rsplit('/', 1)[0],
                    'Publish · ' + node['publisher_intent'] if publisher else ('Capture · ' if capturing else 'Packages · ') + node['request']['intent']))
    planned = {(c, k): n for c, k, n in observations}
    state = transaction(root, dict(nodes=observations, base=base))
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
        headroom = max(0, CONFIG['settings']['headroom'] - sum(repo == COORDINATOR_NAME
            and str(job['run']) == os.environ.get('GITHUB_RUN_ID') for (repo, _), job in occupied.items()))
        blocked = False
        for priority, _, capture, project, row, node, definitions, cause, kind in sorted(candidates, key=lambda c: c[:4]):
            kind = 'publish' if priority == 0 else kind
            blocked = blocked or kind == 'publish' and publishing
            key = row['id'] + '/' + project
            expected = planned.get((capture, key), base['runs'][capture].get('nodes', {}).get(key))
            if (not blocked and free > (0 if kind == 'publish' else headroom)
                    and state['runs'][capture].get('nodes', {}).get(key) == expected):
                budget = 'publications' if kind == 'publish' else 'builds'
                if node.get(budget, 0) < 3:
                    if kind != 'publish':
                        node['request'] = dict(capture=capture, project=project, target=row['id'], runner=row['runner'], publication=publication,
                                               intent=uuid.uuid4().hex, actor=os.environ['COORDINATOR_ACTOR'],
                                               created=datetime.now(timezone.utc).isoformat(), kind=kind)
                        node.update(cause=cause, waiting=True)
                    request = dict(node['request'])
                    if kind == 'capture':
                        node['request']['root'] = capture
                        request['root'] = capture
                    elif kind == 'build':
                        request['definitions'] = definitions
                    else:
                        node.update(waiting=True, publisher_intent=uuid.uuid4().hex, publish_created=datetime.now(timezone.utc).isoformat())
                        request.update(publish_intent=node['publisher_intent'], run=node['source']['run'], attempt=node['source']['attempt'], job=node['job'], artifact=node['artifact'])
                    state = transaction(root, dict(nodes=[(capture, key, node)], base=state))
                    admitted = copy.deepcopy(node)
                    repo = COORDINATOR if kind in {'publish', 'capture'} else OWNER + '/' + project
                    workflow = ('sign-and-publish-packages.yml' if kind == 'publish' else
                                'orchestrate-packages.yml' if kind == 'capture' else 'build-distribution-packages.yml')
                    if state['runs'][capture]['nodes'].get(key) == admitted:
                        try:
                            ref = api('repos/' + repo)['default_branch']
                            result = api(f'repos/{repo}/actions/workflows/{workflow}/dispatches',
                                         dict(ref=ref, inputs=dict(request=json.dumps(request)), return_run_details=True))
                            if result and result.get('workflow_run_id'):
                                node[budget] = node.get(budget, 0) + 1
                                node['publisher' if kind == 'publish' else 'source'] = (
                                    result['workflow_run_id'] if kind == 'publish' else dict(run=result['workflow_run_id'], attempt=1))
                        except (ApiError, OSError, subprocess.SubprocessError) as error:
                            node['observation'] = failure(error)
                            if isinstance(error, ApiError) and 400 <= error.status < 500 and error.status not in {408, 429} and 'rate limit' not in str(error):
                                node.pop('publisher_intent' if kind == 'publish' else 'request', None)
                                node.update(status='failed', waiting=False, reason='Dispatch rejected: ' + str(error))
                        publishing = publishing or kind == 'publish' and bool(node.get('publisher_intent'))
                        free -= 1
                        number = node.get('publisher') if kind == 'publish' else node.get('source', {}).get('run')
                        state = transaction(root, dict(nodes=[(capture, key, node)], base=state,
                                            acknowledgements=[(capture, key, admitted, number)]))
                else:
                    node.update(status='failed', reason=budget + ' dispatch budget exhausted; operator retry required')
                    state = transaction(root, dict(nodes=[(capture, key, node)], base=state))
    return original != read(root / 'status.json') or any(n['status'] not in TERMINAL for g in state['runs'].values() if g['context'].get('contract') == 3 for n in g.get('nodes', {}).values())


def apply_report(root, request, bundle):
    result = receive(request, bundle)
    state = transaction(root, {})
    key = request['target'] + '/' + request['project']
    node = state['runs'][request['capture']]['nodes'][key]
    base = copy.deepcopy(state)
    later = int(request['attempt']) > node.get('source', {}).get('attempt', 0)
    if node.get('category') != 'excluded' and (node['status'] not in TERMINAL or
            node['status'] != 'published' and (later or request.get('artifact') and not node.get('artifact'))):
        if later:
            node.pop('artifact', None)
            node.pop('publisher', None)
            node.pop('publisher_intent', None)
        receipt = json.loads(result['receipt'])
        artifact = request.get('artifact') or node.get('artifact')
        node.update(source=receipt['source'], job=receipt['job'], job_url=receipt['job_url'], artifact=artifact,
                    status='publishing' if artifact else 'pending')
        transaction(root, dict(nodes=[(request['capture'], key, node)], base=base))
    return None


def authorize_operator():
    actor = os.environ.get('GITHUB_TRIGGERING_ACTOR', os.environ['GITHUB_ACTOR'])
    if actor.endswith('[bot]') or api(f'repos/{COORDINATOR}/collaborators/{actor}/permission')['permission'] not in {'admin', 'write'}:
        raise ValueError('Operator action requires a human with write access to ' + COORDINATOR)
    return None


def main():
    command, *args = sys.argv[1:]
    values = {}
    if command == 'notify':
        if not re.fullmatch(TAG, os.environ['GITHUB_REF_NAME']):
            raise ValueError('Only semantic version tags notify the coordinator')
        ref = api('repos/' + COORDINATOR)['default_branch']
        api(f'repos/{COORDINATOR}/actions/workflows/orchestrate-packages.yml/dispatches', dict(ref=ref, inputs=dict(request=json.dumps(dict(
            project=os.environ['GITHUB_REPOSITORY'].split('/')[1], tag=os.environ['GITHUB_REF_NAME'], sha=os.environ['GITHUB_SHA'], run=os.environ['GITHUB_RUN_ID'],
            definition=Path('source/ci/packages.json').read_text())))))
    elif command == 'prepare':
        prepare(*(Path(p).resolve() for p in args))
    elif command == 'operator':
        authorize_operator()
    elif command == 'intake':
        values = intake(json.loads(json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())['inputs']['request']))
    elif command == 'retry-capture':
        retry_capture()
    elif command == 'baseline':
        baseline(Path(args[0]), *args[1:])
    elif command == 'authorize':
        request = json.loads(os.environ['PACKAGE_REQUEST'])
        capture_run(request['capture'])
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
        rejected = None
        operator = os.environ.get('PACKAGE_RETRY') or os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and not os.environ.get('PACKAGE_REPORT')
        if operator:
            authorize_operator()
            if not os.environ.get('PACKAGE_REPORT'):
                transaction(root, dict(observation={}))
            if os.environ.get('PACKAGE_RETRY'):
                transaction(root, dict(retry=os.environ['PACKAGE_RETRY']))
        if os.environ.get('PACKAGE_REPORT'):
            try:
                request = json.loads(os.environ['PACKAGE_REPORT'])
                apply_report(root, request, capture_bundle(identity(request['capture']), bundles))
            except Exception as error:
                rejected = error
                print('Callback rejected: ' + str(error), file=sys.stderr)
        if tick(root, bundles) and any(g.get('context', {}).get('contract') == 3 for g in read(root / 'status.json')['runs'].values()):
            run('bash', str(ROOT / 'ci/publish/status.sh'), str(root), 'project')
        if rejected:
            raise rejected
    else:
        raise ValueError('Unknown coordinator command')
    if values:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            for key, value in values.items():
                print(f'{key}={value}', file=output)
    return None


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        capture_failure(error)
        raise
