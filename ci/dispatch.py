"""One coordinator owns admission; GitHub executions and signed feeds supply facts."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

from ci.repository import PROJECTS, ROOT, run, project_revision, unchanged, dependencies
from ci.publish.publication import read, write, published, TERMINAL

COORDINATOR = 'SNodeC/DistributionPackages'
TAG = r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
SHA = r'[0-9a-f]{40}'


class ApiError(RuntimeError):
    def __init__(self, status, message, retry_after=0):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def api(path, payload=None):
    args = ['gh', 'api', '--include', '-H', 'X-GitHub-Api-Version: 2026-03-10', path]
    if payload is not None:
        args += ['--method', 'POST', '--input', '-']
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None, text=True, capture_output=True)
    headers, _, body = result.stdout.replace('\r\n', '\n').partition('\n\n')
    status = re.search(r'HTTP/[\d.]+ (\d+)', headers)
    if result.returncode:
        retry = re.search(r'(?im)^retry-after: ([0-9]+)', headers)
        reset = re.search(r'(?im)^x-ratelimit-reset: ([0-9]+)', headers)
        limited = bool(retry or re.search(r'(?im)^x-ratelimit-remaining: 0$', headers))
        delay = int(retry[1]) if retry else max(0, int(reset[1]) - time.time()) if reset and limited else 0
        raise ApiError(int(status[1]) if status else 0, ('rate limit: ' if limited else '') + result.stderr + body, min(1800, delay))
    return json.loads(body) if body.strip() else None


def listing(path, field):
    rows, page, more = [], 1, True
    while more:
        value = api(path + ('&' if '?' in path else '?') + f'per_page=100&page={page}')
        if value.get('total_count', 0) >= 1000:
            raise ValueError('API search is truncated; refusing to infer absence: ' + path)
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
    if project not in PROJECTS or not re.fullmatch(TAG, tag) or not re.fullmatch(SHA, sha):
        raise ValueError('Release needs a registered project, version tag and exact commit')
    origin = api(f'repos/SNodeC/{project}/actions/runs/{identity(payload["run"])}')
    if (origin['event'] != 'push' or origin['path'] != '.github/workflows/build-distribution-packages.yml'
            or origin['head_repository']['full_name'] != f'SNodeC/{project}'
            or origin['head_branch'] != tag or origin['head_sha'] != sha):
        raise ValueError('Release notification does not match the upstream tag workflow')
    runs = listing(f'repos/{COORDINATOR}/actions/workflows/orchestrate-packages.yml/runs?created=>=' + origin['created_at'], 'workflow_runs')
    duplicate = any(item['display_title'] == f'Release · {project} · {tag} · {payload["run"]}'
                    and int(item['id']) < int(os.environ['GITHUB_RUN_ID']) for item in runs)
    return dict(project=project, tag=tag, sha=sha, duplicate=str(duplicate).lower())


def capture_run(capture):
    origin = api(f'repos/{COORDINATOR}/actions/runs/{identity(capture)}')
    if (origin['event'] != 'workflow_dispatch' or origin['path'] != '.github/workflows/orchestrate-packages.yml'
            or origin['head_repository']['full_name'] != COORDINATOR):
        raise ValueError('Capture must belong to the coordinator workflow')
    return origin


def retry_capture():
    for attempt in range(1, int(os.environ['GITHUB_RUN_ATTEMPT'])):
        jobs = listing(f'repos/{COORDINATOR}/actions/runs/{identity(os.environ["GITHUB_RUN_ID"])}/attempts/{attempt}/jobs', 'jobs')
        if any(step['name'] == 'Save immutable release capture' and step.get('conclusion') == 'success'
               for job in jobs for step in job.get('steps', [])):
            raise ValueError('Previously saved capture is unavailable; refusing to recapture this generation')


def ready(profile, revisions, project, info, projects=None):
    projects = PROJECTS if projects is None else projects
    result = True
    for dependency in dependencies(project, projects):
        expected = int(revisions[dependency]) if dependency in revisions else project_revision(profile['baseline'], dependency)
        result = result and (project_revision(info, dependency) == expected
                             and info.get('sources', {}).get(dependency) == profile['sources'].get(dependency))
    return result


def baseline(bundle, target, ref):
    from ci.repository import fetch
    if not re.fullmatch(SHA, ref):
        raise ValueError('Dependency publication must be an exact commit')
    project = os.environ['BUILD_PROJECT']
    if PROJECTS[project]['depends_on']:
        row = next(row for row in read(bundle / 'targets.json') if row['id'] == target)
        profile = read(bundle / 'profiles.json')[target]
        info = json.loads(fetch(f'https://raw.githubusercontent.com/SNodeC/Packages/{ref}/{profile["directory"]}/build.json'))
        info = info.get('targets', {}).get(row['arch'], info)
        if not ready(profile, read(bundle / 'revisions.json'), project, info):
            raise ValueError('Dependency is not the corresponding captured publication')
        write(Path('published-snodec/build.json'), info)


def gate(request, state, repository, owner, kind):
    permit = state.get('permits', {}).get(request['intent'], {})
    if (permit.get('kind') != kind or permit.get('owner') != owner or permit.get('repository') != repository
            or any(permit.get(key) != request.get(key) for key in ('capture', 'project', 'target', 'publication'))):
        raise ValueError('Execution has no matching coordinator permit')
    return permit


def authorize(request, bundle):
    capture_run(request['capture'])
    context = read(bundle / 'context.json')
    row = next(row for row in read(bundle / 'targets.json') if row['id'] == request['target'])
    if (context.get('contract') != 2 or context['run_id'] != request['capture']
            or os.environ['GITHUB_REPOSITORY'] != 'SNodeC/' + request['project']
            or request['runner'] != row['runner'] or os.environ.get('RUNNER_ARCH') != ('ARM64' if row['runner'] == 'ubuntu-24.04-arm' else 'X64')
            or request['project'] not in read(bundle / 'revisions.json')
            or row['family'] not in context['projects'][request['project']]['families']
            or not re.fullmatch(SHA, request['publication'])):
        raise ValueError('Build request does not match captured identity/runner/dependencies')
    unchanged(bundle)
    wait_for_permit(request, 'build')
    return dict(row=json.dumps(row), revision=read(bundle / 'revisions.json')[request['project']])


def wait_for_permit(request, kind):
    deadline, allowed = time.monotonic() + 60, False
    while not allowed and time.monotonic() < deadline:
        try:
            with urllib.request.urlopen('https://raw.githubusercontent.com/SNodeC/Packages/main/status.json', timeout=10) as response:
                permit = gate(request, json.load(response), os.environ['GITHUB_REPOSITORY'],
                     dict(run=int(os.environ['GITHUB_RUN_ID']), attempt=int(os.environ['GITHUB_RUN_ATTEMPT'])), kind)
            allowed = True
        except (ValueError, OSError):
            time.sleep(2)
    if not allowed:
        raise ValueError('Permit not bound within 60 seconds; no project code was executed')
    return permit


def transaction(root, payload):
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'control.json'
        write(path, payload)
        run('bash', str(ROOT / 'ci/publish/status.sh'), str(root), 'control', str(path))
    return read(root / 'status.json')


def change(root, payload):
    from ci.publish.publication import migrate
    state = read(root / 'status.json', dict(repository='SNodeC/Packages', branch='main', counters={}, runs={}))
    migrate(state)
    if 'permits' in payload:
        state['permits'] = payload['permits']
    for capture, key, item in payload.get('observations', []):
        state['runs'][capture].setdefault('nodes', {})[key] = item
    if payload.get('retry'):
        capture, project, target = payload['retry'].split('/')
        if any(p['capture'] == capture and p['project'] == project and p['target'] == target for p in state.get('permits', {}).values()):
            raise ValueError('Cannot retry while an execution is admitted')
        node = state['runs'][capture]['nodes'][target + '/' + project]
        state['runs'][capture]['nodes'][target + '/' + project] = ({k: v for k, v in node.items() if k in {'artifact', 'source', 'job', 'job_url'}} | dict(status='pending', attempt=0))
    write(root / 'status.json', state)


def validate_run(permit, origin, intent):
    expected = '.github/workflows/' + ('build-distribution-packages.yml' if permit['kind'] == 'build' else 'sign-and-publish-packages.yml')
    if (origin['event'] != 'workflow_dispatch' or origin['path'] != expected
            or origin['head_repository']['full_name'] != permit['repository']
            or origin['head_branch'] != permit['ref'] or origin['actor']['login'] != permit['actor']
            or origin['display_title'] != 'Packages · ' + intent):
        raise ValueError('Run does not match its coordinator request')
    if permit['kind'] == 'build' and not any(r['path'] == COORDINATOR + '/.github/workflows/build-packages.yml@main'
            and subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', r['sha'], 'HEAD'], capture_output=True).returncode == 0
            for r in origin.get('referenced_workflows', [])):
        raise ValueError('Source run did not use trusted coordinator workflow history')


def observe(state):
    origins = {}
    for project in PROJECTS:
        for status in ('queued', 'in_progress', 'pending', 'waiting', 'requested'):
            for origin in listing(f'repos/SNodeC/{project}/actions/workflows/build-distribution-packages.yml/runs?status={status}', 'workflow_runs'):
                origins[('SNodeC/' + project, origin['id'])] = origin
    for permit in state.get('permits', {}).values():
        if permit.get('owner'):
            repo, owner = permit['repository'], permit['owner']
            origin = api(f'repos/{repo}/actions/runs/{owner["run"]}/attempts/{owner["attempt"]}')
            origins[repo, owner['run']] = max((origin, origins.get((repo, owner['run']), origin)), key=lambda r: r['run_attempt'])
        else:
            workflow = 'build-distribution-packages.yml' if permit['kind'] == 'build' else 'sign-and-publish-packages.yml'
            for origin in listing(f'repos/{permit["repository"]}/actions/workflows/{workflow}/runs?created=>=' + permit['created'], 'workflow_runs'):
                origins[permit['repository'], origin['id']] = origin
    return origins


def tick(root, bundles):
    state = transaction(root, {})
    origins, now = observe(state), time.time()
    permits = dict(state.get('permits', {}))
    observations = []
    for intent, permit in list(permits.items()):
        matches = sorted((r for (repo, _), r in origins.items() if repo == permit['repository'] and r['display_title'] == 'Packages · ' + intent), key=lambda r: r['id'])
        if not permit.get('owner') and matches:
            validate_run(permit, matches[0], intent)
            permit['owner'] = dict(run=matches[0]['id'], attempt=matches[0]['run_attempt'])
        if permit.get('owner'):
            owner = permit['owner']
            origin = origins[permit['repository'], owner['run']]
            if origin['run_attempt'] != owner['attempt']:
                origin = api(f'repos/{permit["repository"]}/actions/runs/{owner["run"]}/attempts/{owner["attempt"]}')
            validate_run(permit, origin, intent)
            generation = state['runs'][permit['capture']]
            key = permit['target'] + '/' + permit['project']
            node = dict(generation.get('nodes', {}).get(key, {}))
            settled = permit['kind'] == 'publish'
            if permit['kind'] == 'build':
                if any(node.get('source', {}).get(k) != v for k, v in owner.items()):
                    node.pop('job', None)
                    node.pop('job_url', None)
                node.update(source=owner | {k: permit[k] for k in ('publication', 'ref', 'actor')} | dict(intent=intent), attempt=owner['attempt'], status='pending' if origin['status'] != 'in_progress' else 'running')
                job, known = {}, False
                try:
                    jobs = listing(f'repos/{permit["repository"]}/actions/runs/{owner["run"]}/attempts/{owner["attempt"]}/jobs', 'jobs')
                    job = next((j for j in jobs if j['name'] == 'build / ' + permit['target'] and j['run_attempt'] == owner['attempt']), {})
                    known = True
                    if job:
                        node.update(job=job['id'], job_url=job['html_url'])
                except (ApiError, ValueError) as error:
                    print(f'::warning::Job discovery deferred: {error}')
                try:
                    if origin['status'] == 'completed':
                        artifacts = listing(f'repos/{permit["repository"]}/actions/runs/{owner["run"]}/artifacts', 'artifacts')
                        artifact = next((a for a in artifacts if a['name'] == f'packages-{permit["project"]}-{permit["target"]}-{owner["attempt"]}' and not a['expired']), None)
                        if artifact and re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest') or '') and node.get('job') and (not job or any(s['name'] == 'Upload package artifact' and s.get('conclusion') == 'success' for s in job.get('steps', []))):
                            node.update(artifact=dict(id=artifact['id'], digest=artifact['digest']), status='publishing')
                            settled = True
                        elif known or not artifact:
                            node.update(status='cancelled' if origin['conclusion'] == 'cancelled' else 'failed', reason='Source execution ended without a usable package artifact')
                            settled = True
                        if job and any(s['name'] == 'Authorize build permit' and s.get('conclusion') == 'failure' for s in job.get('steps', [])) and node.get('dispatches', 0) < 3:
                            node['status'] = 'pending'
                except (ApiError, ValueError) as error:
                    print(f'::warning::Artifact observation deferred: {error}')
            elif origin['status'] == 'completed' and origin['conclusion'] != 'success':
                node.update(status='failed', reason='Publication failed; repair and retry this task')
            observations.append((permit['capture'], key, node))
            if origin['status'] == 'completed' and settled:
                del permits[intent]
        elif now - permit['sent_at'] >= 120:
            del permits[intent]
    # Persist closed intents before reusing their capacity. Late runs cannot pass the gate.
    state = transaction(root, dict(permits=permits, observations=observations))
    candidates = []
    for capture, generation in state['runs'].items():
        if generation['context'].get('contract') == 2 and (not generation.get('nodes') or any(n['status'] not in {'published', 'superseded'} for n in generation['nodes'].values())):
            if capture not in bundles:
                directory = Path(os.environ['RUNNER_TEMP']) / 'package-captures' / capture
                try:
                    if not (directory / 'context.json').exists():
                        run('gh', 'run', 'download', capture, '--repo', COORDINATOR, '-n', 'source-pair', '-D', str(directory))
                    unchanged(directory)
                    bundles[capture] = directory
                except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
                    print(f'::warning::Capture unavailable; recover generation {capture}: {error}')
                    observations.extend((capture, row['id'] + '/' + project, generation.get('nodes', {}).get(row['id'] + '/' + project, dict(attempt=0)) | dict(status='failed', reason='Immutable capture unavailable; restore artifact or capture a new generation'))
                                        for row in generation['targets'] for project in generation['revisions']
                                        if row['family'] in generation['context']['projects'][project]['families'] and generation.get('nodes', {}).get(row['id'] + '/' + project, {}).get('status') not in TERMINAL)
            bundle = bundles.get(capture)
            if bundle:
                from ci.publish.publication import record_run
                record_run(bundle, state, read(bundle / 'context.json'))
                profiles = read(bundle / 'profiles.json')
                projects = generation['context']['projects']
                for row in generation['targets']:
                    info, _ = published(root, row)
                    for project in generation['revisions']:
                        if row['family'] in projects[project]['families']:
                            key = row['id'] + '/' + project
                            node = dict(generation.get('nodes', {}).get(key, dict(status='pending', attempt=0)))
                            manual = origins.get(('SNodeC/' + project, node.get('source', {}).get('run')))
                            if manual and manual['run_attempt'] > node.get('attempt', 0) and node['status'] in {'failed', 'cancelled'} and not node.get('artifact'):
                                node.update(status='pending', attempt=manual['run_attempt'])
                            receipt = info.get('publications', {}).get(project, {})
                            if receipt.get('capture') == capture and receipt.get('revision') == generation['revisions'][project]:
                                node.update(status='published', job_url=receipt['job_url'], published_at=receipt['published_at'])
                            elif not generation['sources'].get(project):
                                node.update(status='skipped', reason='No matching release tag existed at capture')
                            elif project_revision(info, project) > int(generation['revisions'][project]):
                                node.update(status='superseded', reason='A newer project revision is already published')
                            elif any((project_revision(info, d) > (int(generation['revisions'][d]) if d in generation['revisions'] else project_revision(profiles[row['id']]['baseline'], d)) or project_revision(info, d) == (int(generation['revisions'][d]) if d in generation['revisions'] else project_revision(profiles[row['id']]['baseline'], d)) and info.get('sources', {}).get(d) != profiles[row['id']]['sources'].get(d)) for d in dependencies(project, projects)):
                                node.update(status='superseded', reason='A captured dependency has been replaced in the feed')
                            if node['status'] not in TERMINAL and not node.get('source') and any(generation.get('nodes', {}).get(row['id'] + '/' + d, {}).get('status') in {'failed', 'cancelled', 'skipped'} for d in dependencies(project, projects)):
                                node.update(status='skipped', reason='Waiting for failed prerequisite to be retried')
                            if node['status'] == 'skipped' and generation['sources'].get(project) and ready(profiles[row['id']], generation['revisions'], project, info, projects):
                                node['status'] = 'pending'
                            if node['status'] not in TERMINAL and ready(profiles[row['id']], generation['revisions'], project, info, projects):
                                kind = 'publish' if node.get('artifact') else 'build'
                                if not any(p['capture'] == capture and p['project'] == project and p['target'] == row['id'] for p in permits.values()):
                                    candidates.append((kind != 'publish', not bool(projects[project]['depends_on']), generation['context']['captured_at'], capture, project, row, node, kind))
                            observations.append((capture, key, node))
    state = transaction(root, dict(permits=permits, observations=observations))
    occupied = {(repo, r['id']) for (repo, _), r in origins.items() if repo != COORDINATOR and r['status'] != 'completed'}
    occupied.update((p['repository'], p['owner']['run']) for p in permits.values() if p['kind'] == 'build' and p.get('owner'))
    build_count = len(occupied) + sum(p['kind'] == 'build' and not p.get('owner') for p in permits.values())
    ordered = sorted(candidates, key=lambda c: c[:5])
    roots = [c for c in ordered if c[1] and c[-1] == 'build']
    if roots:
        ordered.remove(roots[0])
        ordered.insert(max(0, 15 - build_count), roots[0])
    for _, _, _, capture, project, row, node, kind in ordered:
        slow = row['arch'] if row['family'] == 'linux' and row['arch'] in {'armhf', 'riscv64'} else None
        manual = origins.get(('SNodeC/' + project, node.get('source', {}).get('run')))
        retry = kind == 'build' and manual and manual['run_attempt'] > node.get('source', {}).get('attempt', 0)
        if (kind == 'publish' and not any(p['kind'] == kind for p in permits.values()) or kind == 'build' and build_count - bool(retry) < 16
                and (not slow or not any(p.get('slow') == slow for p in permits.values()))):
            repo = COORDINATOR if kind == 'publish' else 'SNodeC/' + project
            intent = node['source']['intent'] if retry else uuid.uuid4().hex
            permit = dict(kind=kind, capture=capture, project=project, target=row['id'], repository=repo, slow=slow,
                          publication=run('git', '-C', str(root), 'rev-parse', 'HEAD'), sent_at=now,
                          created=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)), actor=os.environ['COORDINATOR_ACTOR'],
                          ref=api('repos/' + repo)['default_branch'], source=node)
            if retry:
                permit.update({k: node['source'][k] for k in ('publication', 'ref', 'actor')}, owner=dict(run=manual['id'], attempt=manual['run_attempt']))
                validate_run(permit, manual, intent)
            permits[intent] = permit
            node['dispatches'] = node.get('dispatches', 0) + 1
            if node['dispatches'] > 3:
                del permits[intent]
                node.update(status='failed', reason='Dispatch recovery exhausted; correct configuration and retry task')
            transaction(root, dict(observations=[(capture, row['id'] + '/' + project, node)]))
            transaction(root, dict(permits=permits))
            request = {k: permit[k] for k in ('capture', 'project', 'target', 'publication')}
            request.update(intent=intent, runner=row['runner'])
            try:
                if intent in permits and not retry:
                    workflow = 'sign-and-publish-packages.yml' if kind == 'publish' else 'build-distribution-packages.yml'
                    result = api(f'repos/{repo}/actions/workflows/{workflow}/dispatches', dict(ref=permit['ref'], inputs=dict(request=json.dumps(request)), return_run_details=True))
                    origin = api(f'repos/{repo}/actions/runs/{result["workflow_run_id"]}')
                    validate_run(permit, origin, intent)
                    permit['owner'] = dict(run=origin['id'], attempt=origin['run_attempt'])
                    transaction(root, dict(permits=permits))
            except ApiError as error:
                print(f'::warning::Dispatch unconfirmed: {error}')
                if error.retry_after:
                    permit['sent_at'] = now + max(0, error.retry_after - 120)
                    transaction(root, dict(permits=permits))
                if error.status in {400, 401, 404, 422} or error.status == 403 and 'rate limit' not in str(error).lower():
                    del permits[intent]
                    node.update(status='failed', reason=str(error))
                    transaction(root, dict(permits=permits, observations=[(capture, row['id'] + '/' + project, node)]))
            build_count += kind == 'build' and not retry
    return bool(permits)


def receive(request, bundle):
    capture_run(request['capture'])
    permit = wait_for_permit(request, 'publish')
    source = permit['source']
    origin = api(f'repos/SNodeC/{request["project"]}/actions/runs/{source["source"]["run"]}/attempts/{source["source"]["attempt"]}')
    source_permit = permit | dict(kind='build', repository='SNodeC/' + request['project'], ref=source['source']['ref'], actor=source['source']['actor'])
    validate_run(source_permit, origin, source['source']['intent'])
    row = next(r for r in read(bundle / 'targets.json') if r['id'] == request['target'])
    job = api(f'repos/SNodeC/{request["project"]}/actions/jobs/{identity(source["job"])}')
    if (job['run_id'] != source['source']['run'] or job['run_attempt'] != source['source']['attempt']
            or job['name'] != 'build / ' + request['target'] or job['html_url'] != source['job_url']):
        raise ValueError('Publication job does not match admitted source execution')
    artifact = api(f'repos/SNodeC/{request["project"]}/actions/artifacts/{source["artifact"]["id"]}')
    if (artifact['expired'] or artifact['digest'] != source['artifact']['digest']
            or artifact['workflow_run']['id'] != source['source']['run']
            or artifact['name'] != f'packages-{request["project"]}-{request["target"]}-{source["source"]["attempt"]}'):
        raise ValueError('Source artifact expired or changed')
    receipt = dict(capture=request['capture'], source=source['source'], artifact=source['artifact'],
                   job=source['job'], job_url=source['job_url'], tooling=read(bundle / 'context.json')['recipe_commit'])
    return dict(receipt=json.dumps(receipt), target=json.dumps(row), project=request['project'], run=source['source']['run'], attempt=source['source']['attempt'],
                artifact=artifact['name'], artifact_id=artifact['id'], artifact_digest=artifact['digest'], job=source['job'], run_url=source['job_url'])


def main():
    command, *args = sys.argv[1:]
    values = {}
    if command == 'notify':
        if not re.fullmatch(TAG, os.environ['GITHUB_REF_NAME']):
            raise ValueError('Only semantic version tags notify the coordinator')
        api(f'repos/{COORDINATOR}/actions/workflows/orchestrate-packages.yml/dispatches', dict(ref='main', inputs=dict(
            project=os.environ['GITHUB_REPOSITORY'].split('/')[1], tag=os.environ['GITHUB_REF_NAME'], sha=os.environ['GITHUB_SHA'], run=os.environ['GITHUB_RUN_ID'])))
    elif command == 'intake':
        values = intake(json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())['inputs'])
    elif command == 'retry-capture':
        retry_capture()
    elif command == 'baseline':
        baseline(Path(args[0]), *args[1:])
    elif command == 'authorize':
        values = authorize(json.loads(os.environ['PACKAGE_REQUEST']), Path(args[0]))
    elif command == 'receive':
        values = receive(json.loads(os.environ['PACKAGE_REQUEST']), Path(args[0]))
    elif command == 'control':
        root, bundles = Path(args[0]), {}
        if os.environ.get('PACKAGE_RETRY'):
            transaction(root, dict(retry=os.environ['PACKAGE_RETRY']))
        deadline, active = time.monotonic() + 2700, True
        while active and time.monotonic() < deadline:
            try:
                active = tick(root, bundles)
            except (ApiError, ValueError, subprocess.CalledProcessError, OSError) as error:
                print(f'::warning::Coordinator observation deferred: {error}')
            process = subprocess.Popen(['bash', str(ROOT / 'ci/publish/status.sh'), str(root), 'project'], start_new_session=True)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                print('::warning::Presentation timeout; control and publication remain independent')
            if active:
                time.sleep(60)
        if active:
            api(f'repos/{COORDINATOR}/actions/workflows/control-packages.yml/dispatches', dict(ref='main', inputs={}))
    else:
        raise ValueError('Unknown coordinator operation')
    if values:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            for key, value in values.items():
                print(f'{key}={value}', file=output)


if __name__ == '__main__':
    main()
