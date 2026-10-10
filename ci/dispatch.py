"""Authenticated handoffs; the capture and existing publication state stay authoritative."""
import json
import os
import re
from pathlib import Path
import sys

from ci.repository import REPOSITORIES, run
from ci.publish.publication import read, targets


def api(path, payload=None):
    args = ['gh', 'api', path]
    if payload is not None:
        args += ['--method', 'POST', '--input', '-']
    result = run(*args, input=json.dumps(payload) if payload is not None else None)
    return json.loads(result) if result else None


def build(bundle, project, target, publication):
    if project != 'mqttsuite' or target not in {row['id'] for row in targets()}:
        raise ValueError('Unknown build project/target')
    capture = read(bundle / 'context.json')['run_id']
    # Retry a handoff, not a completed build. GitHub remains the run authority.
    title = f'Packages · {capture} · {target}'
    for page in json.loads(run('gh', 'api', '--paginate', '--slurp',
            f'repos/SNodeC/{project}/actions/runs?event=repository_dispatch&per_page=100&created=>=' +
            read(bundle / 'context.json')['captured_at'])):
        if any(item['display_title'] == title for item in page['workflow_runs']):
            return
    api(f'repos/SNodeC/{project}/dispatches', dict(event_type='package-build', client_payload=dict(
        capture=capture, target=target, publication=publication)))


def receive(payload):
    project = payload['project']
    if project not in REPOSITORIES:
        raise ValueError('Unknown artifact repository')
    row = next(row for row in targets() if row['id'] == payload['target'])
    capture, build_run, attempt = (str(payload[key]) for key in ('capture', 'run', 'attempt'))
    if not all(value.isdecimal() and int(value) > 0 for value in (capture, build_run, attempt)):
        raise ValueError('Invalid run identity')
    origin = api(f'repos/SNodeC/{project}/actions/runs/{build_run}')
    if (origin['event'] not in {'push', 'repository_dispatch'} or origin['path'] != '.github/workflows/packages.yml'
            or origin['head_repository']['full_name'] != f'SNodeC/{project}'
            or origin['run_attempt'] < int(attempt)):
        raise ValueError('Artifact must come from the current upstream package build attempt')
    if origin['display_title'] not in {f'Packages · {capture} · -', f'Packages · {capture} · {row["id"]}'}:
        raise ValueError('Build belongs to a different captured release')
    if origin['event'] == 'push':
        if capture != build_run or not re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', origin['head_branch']):
            raise ValueError('Capture must be the originating version-tag run')
    elif project != 'mqttsuite' or origin['display_title'] != f'Packages · {capture} · {row["id"]}':
        raise ValueError('Only a published SNode.C target dispatches a dependent build')
    name = f'packages-{project}-{row["id"]}-{attempt}'
    return dict(project=project, target=json.dumps(row), capture=capture, run=build_run,
                attempt=attempt, artifact=name, run_url=origin['html_url'],
                capture_repository='SNodeC/' + (project if origin['event'] == 'push' else 'snode.c'))


def baseline(bundle, target, ref):
    """Load exactly the SNode.C publication dispatched to this application build."""
    from ci.repository import fetch
    row = next(row for row in targets() if row['id'] == target)
    profile = read(bundle / 'profiles.json')[target]
    info = json.loads(fetch(f'https://raw.githubusercontent.com/SNodeC/Packages/{ref}/{profile["directory"]}/build.json'))
    info = info.get('targets', {}).get(row['arch'], info)
    context = read(bundle / 'context.json')
    revisions = read(bundle / 'revisions.json')
    if (info['context']['run_id'] != context['run_id'] or info['sources']['snode.c'] != profile['sources']['snode.c']
            or info['context']['build_project'] != 'snode.c' or str(info['revision']) != revisions['snode.c']):
        raise ValueError('Dependency is not the corresponding published SNode.C build')
    directory = Path('published-snodec')
    directory.mkdir()
    (directory / 'build.json').write_text(json.dumps(info))


if __name__ == '__main__':
    command, *args = sys.argv[1:]
    if command == 'receive':
        values = receive(json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())['client_payload'])
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            for key, value in values.items():
                print(f'{key}={value}', file=output)
    elif command == 'plan':
        bundle, project, target = Path(args[0]), args[1], args[2]
        context = read(bundle / 'context.json')
        if (context['run_id'] != os.environ['CAPTURE_RUN']
                or (target == '-' and project != context['release_project'])
                or (target != '-' and (project != 'mqttsuite' or context['release_project'] != 'snode.c'))):
            raise ValueError('Build request does not match capture')
        if target != '-' and not re.fullmatch(r'[0-9a-f]{40}', os.environ.get('PUBLISHED_REF', '')):
            raise ValueError('Dependent build requires an exact Packages commit')
        rows = [row for row in read(bundle / 'targets.json') if target in {'-', row['id']}]
        if not rows:
            raise ValueError('Unknown target')
        print('matrix=' + json.dumps({'include': rows}))
        print('revisions=' + json.dumps(read(bundle / 'revisions.json')))
    elif command == 'built':
        bundle, target, project = args
        capture = read(Path(bundle) / 'context.json')['run_id']
        api('repos/SNodeC/DistributionPackages/dispatches', dict(event_type='package-built', client_payload=dict(
            capture=capture, project=project, target=target, run=os.environ['GITHUB_RUN_ID'],
            attempt=os.environ['GITHUB_RUN_ATTEMPT'])))
    else:
        {'build': build, 'baseline': baseline}[command](Path(args[0]), *args[1:])
