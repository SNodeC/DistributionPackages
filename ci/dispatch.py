"""Authenticated release intake and build/publication handoffs owned by the coordinator."""
import json
import os
import re
from pathlib import Path
import sys

from ci.repository import PROJECTS, REPOSITORIES, supports, run, project_revision
from ci.publish.publication import read, published

COORDINATOR = 'SNodeC/DistributionPackages'
TAG = r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
SHA = r'[0-9a-f]{40}'


def api(path, payload=None):
    args = ['gh', 'api', path]
    if payload is not None:
        args += ['--method', 'POST', '--input', '-']
    result = run(*args, input=json.dumps(payload) if payload is not None else None)
    return json.loads(result) if result else None


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
    duplicate = False
    if os.environ.get('GITHUB_RUN_ID'):
        title = f'Release · {project} · {tag} · {payload["run"]}'
        pages = json.loads(run('gh', 'api', '--paginate', '--slurp',
            f'repos/{COORDINATOR}/actions/workflows/orchestrate-packages.yml/runs?event=repository_dispatch&per_page=100'))
        duplicate = any(item['display_title'] == title and int(item['id']) < int(os.environ['GITHUB_RUN_ID'])
                        for page in pages for item in page['workflow_runs'])
    return dict(project=project, tag=tag, sha=sha, duplicate=str(duplicate).lower())


def capture_run(capture):
    origin = api(f'repos/{COORDINATOR}/actions/runs/{identity(capture)}')
    if (origin['event'] != 'repository_dispatch' or origin['path'] != '.github/workflows/orchestrate-packages.yml'
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


def build(bundle, project, target, publication):
    context = read(bundle / 'context.json')
    rows = read(bundle / 'targets.json')
    if (project not in read(bundle / 'revisions.json') or not re.fullmatch(SHA, publication)
            or (target == '-' and project != context['release_project'])
            or (target != '-' and not any(row['id'] == target and supports(project, row) for row in rows))):
        raise ValueError('Unknown build project/target or publication')
    capture = context['run_id']
    title = f'Packages · {capture} · {target}'
    pages = json.loads(run('gh', 'api', '--paginate', '--slurp',
        f'repos/SNodeC/{project}/actions/runs?event=repository_dispatch&per_page=100&created=>=' + context['captured_at']))
    exists = any(item['display_title'] == title and item['path'] == '.github/workflows/build-distribution-packages.yml'
                 for page in pages for item in page['workflow_runs'])
    if not exists:
        api(f'repos/SNodeC/{project}/dispatches', dict(event_type='build-packages', client_payload=dict(
            capture=capture, target=target, publication=publication)))


def receive(payload, bundle, action):
    project = payload['project']
    if project not in REPOSITORIES:
        raise ValueError('Unknown artifact repository')
    status = payload.get('status', 'publishing')
    if (status not in {'running', 'publishing', 'failed', 'cancelled'}
            or action not in {'sign-and-publish-packages', 'package-build-status'}
            or (status == 'publishing') != (action == 'sign-and-publish-packages')):
        raise ValueError('Invalid build status')
    target = payload['target']
    capture, build_run, attempt = (identity(payload[key]) for key in ('capture', 'run', 'attempt'))
    capture_run(capture)
    origin = api(f'repos/SNodeC/{project}/actions/runs/{build_run}')
    if (origin['event'] != 'repository_dispatch' or origin['path'] != '.github/workflows/build-distribution-packages.yml'
            or origin['head_repository']['full_name'] != f'SNodeC/{project}' or origin['run_attempt'] < int(attempt)
            or origin['display_title'] not in {f'Packages · {capture} · -', f'Packages · {capture} · {target}'}):
        raise ValueError('Result does not match the upstream build workflow and capture')
    context = read(bundle / 'context.json')
    rows = [row for row in read(bundle / 'targets.json') if supports(project, row) and target in {'-', row['id']}]
    if (context['run_id'] != capture or project not in read(bundle / 'revisions.json') or not rows
            or (target == '-' and (project != context['release_project'] or status not in {'failed', 'cancelled'}))):
        raise ValueError('Result does not belong to the captured project and target')
    row = rows[0] if target != '-' else None
    job_url, final_targets = origin['html_url'], None
    if 'job' in payload:
        job = api(f'repos/SNodeC/{project}/actions/jobs/{identity(payload["job"])}')
        name = f"{row['distribution']} · {row['suite']} · {row['arch']}" if row else ''
        if (row is None or str(job['run_id']) != build_run or str(job['run_attempt']) != attempt
                or job['name'] not in {name, 'build / ' + name}):
            raise ValueError('Job does not belong to the validated target and attempt')
        job_url = job['html_url']
    else:
        if status not in {'failed', 'cancelled'}:
            raise ValueError('Only finalization may omit its build job')
        pages = json.loads(run('gh', 'api', '--paginate', '--slurp',
            f'repos/SNodeC/{project}/actions/runs/{build_run}/jobs?filter=all&per_page=100'))
        jobs = sorted((job for page in pages for job in page['jobs'] if job['run_attempt'] <= int(attempt)),
                      key=lambda job: job['run_attempt'])
        latest = {job['name']: job for job in jobs}
        handed_off = {job['name'] for job in latest.values()
                      if job.get('conclusion') == 'success' or any(step['name'] == 'Request signed publication'
                         and step.get('conclusion') == 'success' for step in job.get('steps', []))}
        final_targets = [row for row in rows if not handed_off.intersection(
            {f"{row['distribution']} · {row['suite']} · {row['arch']}",
             f"build / {row['distribution']} · {row['suite']} · {row['arch']}"})]
    return dict(project=project, target=json.dumps(row), final_targets=json.dumps(final_targets), capture=capture,
                run=build_run, attempt=attempt, artifact=f'packages-{project}-{target}-{attempt}', status=status,
                run_url=job_url, capture_repository=COORDINATOR)


def ready(profile, revisions, project, info):
    result = True
    for dependency in PROJECTS[project]['depends_on']:
        expected = int(revisions[dependency]) if dependency in revisions else project_revision(profile['baseline'], dependency)
        result = result and (project_revision(info, dependency) == expected
                             and info.get('sources', {}).get(dependency) == profile['sources'].get(dependency))
    return result


def baseline(bundle, target, ref):
    """Verify the exact signed snapshot against every captured build dependency."""
    from ci.repository import fetch
    if not re.fullmatch(SHA, ref):
        raise ValueError('Dependency publication must be an exact commit')
    if PROJECTS[os.environ['BUILD_PROJECT']]['depends_on']:
        row = next(row for row in read(bundle / 'targets.json') if row['id'] == target)
        profile = read(bundle / 'profiles.json')[target]
        info = json.loads(fetch(f'https://raw.githubusercontent.com/SNodeC/Packages/{ref}/{profile["directory"]}/build.json'))
        info = info.get('targets', {}).get(row['arch'], info)
        if not ready(profile, read(bundle / 'revisions.json'), os.environ['BUILD_PROJECT'], info):
            raise ValueError('Dependency is not the corresponding captured publication')
        directory = Path('published-snodec')
        directory.mkdir()
        (directory / 'build.json').write_text(json.dumps(info))


def plan(bundle, project, target):
    context = read(bundle / 'context.json')
    revisions = read(bundle / 'revisions.json')
    if (context['run_id'] != os.environ['CAPTURE_RUN'] or project not in revisions
            or (target == '-' and project != context['release_project'])
            or not re.fullmatch(SHA, os.environ.get('PUBLISHED_REF', ''))):
        raise ValueError('Build request does not match capture and exact publication')
    rows = [row for row in read(bundle / 'targets.json') if target in {'-', row['id']} and supports(project, row)]
    if not rows:
        raise ValueError('Unknown target')
    return dict(matrix=json.dumps({'include': rows}), revisions=json.dumps(revisions))


def dependents(bundle, target, publication, root):
    row = next(row for row in read(bundle / 'targets.json') if row['id'] == target)
    info, _ = published(Path(root), row)
    revisions = read(bundle / 'revisions.json')
    profile = read(bundle / 'profiles.json')[target]
    for project in revisions:
        if (supports(project, row) and PROJECTS[project]['depends_on']
                and ready(profile, revisions, project, info)
                and project_revision(info, project) < int(revisions[project])):
            build(bundle, project, target, publication)


def report(bundle, target, project, status):
    capture = read(bundle / 'context.json')['run_id']
    event = 'sign-and-publish-packages' if status == 'publishing' else 'package-build-status'
    api(f'repos/{COORDINATOR}/dispatches', dict(event_type=event, client_payload=dict(
        capture=capture, project=project, target=target, status=status, run=os.environ['GITHUB_RUN_ID'],
        attempt=os.environ['GITHUB_RUN_ATTEMPT'], **({'job': os.environ['BUILD_JOB_ID']} if os.environ.get('BUILD_JOB_ID') else {}))))


def main():
    command, *args = sys.argv[1:]
    values = {}
    if command == 'notify':
        if not re.fullmatch(TAG, os.environ['GITHUB_REF_NAME']):
            raise ValueError('Only semantic version tags notify the coordinator')
        api(f'repos/{COORDINATOR}/dispatches', dict(event_type='release-packages', client_payload=dict(
            project=os.environ['GITHUB_REPOSITORY'].split('/')[1], tag=os.environ['GITHUB_REF_NAME'],
            sha=os.environ['GITHUB_SHA'], run=os.environ['GITHUB_RUN_ID'])))
    elif command in {'intake', 'receive'}:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        values = (intake(event['client_payload']) if command == 'intake'
                  else receive(event['client_payload'], Path(args[0]), event['action']))
    elif command == 'retry-capture':
        retry_capture()
    elif command == 'authorize':
        capture_run(os.environ['CAPTURE_RUN'])
    elif command == 'plan':
        values = plan(Path(args[0]), *args[1:])
    elif command in {'built', 'status'}:
        report(Path(args[0]), args[1], args[2], 'publishing' if command == 'built' else args[3])
    elif command == 'start':
        bundle = Path(args[0])
        context = read(bundle / 'context.json')
        build(bundle, context['release_project'], '-', context['packages_commit'])
    else:
        {'build': build, 'baseline': baseline, 'dependents': dependents}[command](Path(args[0]), *args[1:])
    if values:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            for key, value in values.items():
                print(f'{key}={value}', file=output)


if __name__ == '__main__':
    main()
