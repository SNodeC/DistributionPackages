"""Monotonic build events and serialized feed publication for Packages/main."""
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import shutil
import sys

from ci.repository import ROOT, matrix, linux_matrix, run, select, project_file, digest, REPOSITORIES, project_revision


def targets():
    rows = [dict(family='openwrt', distribution='openwrt', suite=r['series'], arch=r['arch'],
                 runner='ubuntu-24.04', build=r) for r in matrix()]
    rows += [dict(family='raspberrypi', distribution='raspberrypios', suite=suite, arch='arm64',
                  runner='ubuntu-24.04-arm', build=dict(suite=suite))
             for suite in json.loads((ROOT / 'ci/targets/raspberrypi.json').read_text())]
    rows += [dict(family='linux', distribution=r['distribution'], suite=r['suite'], arch=r['arch'],
                  runner=r['runner'], build=r) for r in linux_matrix()]
    for index, row in enumerate(rows):
        row['id'] = '-'.join(row[k] for k in ('distribution', 'suite', 'arch'))
        row['build_slot'] = {'linux-armhf': 0, 'linux-riscv64': 1}.get(f"{row['family']}-{row['arch']}", 2 + index % 17)
    return rows


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def feed_paths(row):
    if row['distribution'] in {'debian', 'ubuntu', 'raspberrypios'}:
        return [f"{row['distribution']}/{part}/{row['suite']}" for part in ('dists', 'pool')]
    return [f"{row['distribution']}/{row['suite']}/{row['arch']}"]


def published(root, row):
    path = root / feed_paths(row)[0] / 'build.json'
    info = read(path, {})
    if len(feed_paths(row)) == 2:
        info = info.get('targets', {}).get(row['arch'], info if row['arch'] in info.get('architectures', []) else {})
    return info, path.parent.relative_to(root).as_posix()


TERMINAL = {'published', 'failed', 'cancelled', 'skipped', 'superseded'}
ORDER = {'not built': 0, 'pending': 1, 'running': 2, 'publishing': 3, **dict.fromkeys(TERMINAL, 4)}


def render(root, state):
    badges = root / 'status/badges'
    badges.mkdir(parents=True, exist_ok=True)
    sections = {}
    colors = {'pending': '#57606a', 'running': '#0969da', 'publishing': '#0969da', 'published': '#1a7f37',
              'failed': '#cf222e', 'cancelled': '#57606a', 'skipped': '#57606a', 'superseded': '#9a6700', 'not built': '#57606a'}
    for label, color in colors.items():
        width = len(label) * 7 + 16
        badge = badges / (label.replace(' ', '-') + '.svg')
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="{label}"><rect width="{width}" height="20" rx="3" fill="{color}"/><text x="{width / 2}" y="14" text-anchor="middle" fill="white" font-family="Verdana,sans-serif" font-size="11">{label}</text></svg>\n'
        if not badge.exists():
            badge.write_text(svg)
        elif badge.read_text() != svg:
            raise RuntimeError(f'Immutable badge differs: {badge.name}')
    for obsolete in (root / 'status').glob('*.svg'):
        obsolete.unlink()
    for row in sorted(targets(), key=lambda item: item['arch']):
        info, feed = published(root, row)
        versions = info.get('versions', {})
        snodec = versions.get('snodec', versions.get('snode.c'))
        date = f"[{info['published_at'][:10]}](../{feed}/build.json)" if info.get('published_at') else '—'
        packages = f"{row['distribution']}/pool/{row['suite']}" if row['distribution'] in {'debian', 'ubuntu', 'raspberrypios'} else f'{feed}/Packages' if row['distribution'] in {'rocky', 'fedora'} else feed
        links = f'[Packages](../{packages}/)' if info else '—'
        for project, version in zip(REPOSITORIES, (snodec, versions.get('mqttsuite'))):
            item = state['targets'].get(f"{row['id']}/{project}", {})
            status = item.get('status', 'published' if version else 'not built')
            filename = status.replace(' ', '-') + '.svg'
            badge = f"![{project}: {status}](../status/badges/{filename})"
            url = item.get('job_url', item.get('run_url'))
            badge = f'[{badge}]({url})' if url else badge
            version = f'`{version}`' if version else '—'
            sections.setdefault(row['distribution'], {}).setdefault(row['suite'], {}).setdefault(project, []).append(f"| `{row['arch']}` | {version} | {badge} | {date} | {links} |")
    text = (ROOT / 'ci/templates/package-status.md').read_text()
    for distribution, suites in sections.items():
        tables = []
        for suite, projects in suites.items():
            tables.append(f'### {suite}')
            for project, lines in projects.items():
                title = 'SNode.C' if project == 'snode.c' else 'MQTTSuite'
                tables.append(f'#### {title}\n\n| Architecture | Version | Status | Published | Packages |\n| --- | --- | --- | --- | --- |\n' + '\n'.join(lines))
        text = text.replace(f'<!-- targets:{distribution} -->', '\n\n'.join(tables))
    (root / 'docs').mkdir(exist_ok=True)
    (root / 'docs/status.md').write_text(text)


def update(state, row, generation, project, status, attempt, job_url=None):
    key = f"{row['id']}/{project}"
    previous = state['targets'].get(key, {})
    revision = generation['revisions'][project]
    if status not in ORDER:
        raise ValueError('Unknown status')
    incoming = (int(revision), attempt)
    existing = (int(previous.get('revision', 0)), previous.get('attempt', 0))
    if incoming < existing:
        return
    if incoming == existing and previous:
        if previous['run_id'] != generation['run_id']:
            raise RuntimeError('Two runs claim the same project revision and attempt')
        if previous['status'] in TERMINAL or ORDER[status] <= ORDER[previous['status']]:
            return
    state['targets'][key] = dict(target=row, revision=revision, attempt=attempt,
                                run_id=generation['run_id'], run_url=generation['run_url'], status=status,
                                job_url=job_url or (previous.get('job_url') if previous.get('run_id') == generation['run_id']
                                                   and previous.get('attempt') == attempt else None) or generation['run_url'])


def reserve(root, project, run_id):
    """Called under the same publication lock as every snapshot writer."""
    if project not in REPOSITORIES:
        raise ValueError('Unknown release project')
    path = root / 'status.json'
    state = read(path, dict(repository='SNodeC/Packages', branch='main', runs={}, targets={}))
    allocations = state.setdefault('allocations', {})
    selected = REPOSITORIES if project == 'snode.c' else (project,)
    if run_id not in allocations:
        floors = {repo: int(os.environ.get('PACKAGE_REVISION_BASE', '0')) for repo in REPOSITORIES}
        for values in [*allocations.values(), *(r['revisions'] for r in state.get('runs', {}).values())]:
            for repo, value in values.items():
                floors[repo] = max(floors[repo], int(value))
        for row in targets():
            info, _ = published(root, row)
            for repo in REPOSITORIES:
                floors[repo] = max(floors[repo], project_revision(info, repo))
        allocations[run_id] = {repo: str(floors[repo] + 1) for repo in selected}
    if set(allocations[run_id]) != set(selected):
        raise RuntimeError('A retry cannot change its release project')
    write(path, state)
    return allocations[run_id]


def record_run(bundle, state, context):
    run_id = context['run_id']
    rows = read(bundle / 'targets.json')
    revisions = read(bundle / 'revisions.json')
    generation = state['runs'].get(run_id)
    if generation:
        if (generation['revisions'] != revisions or generation['context'] != context or generation['sources'] != read(bundle / 'sources.json')
                or generation['targets'] != rows or generation['profiles_hash'] != digest(bundle / 'profiles.json')):
            raise RuntimeError('A retry cannot change its captured sources or matrix')
    else:
        generation = dict(revision=revisions['mqttsuite'], revisions=revisions, context=context, sources=read(bundle / 'sources.json'),
                          targets=rows, profiles_hash=digest(bundle / 'profiles.json'), run_id=run_id, run_url=context['run_url'])
        state['runs'][run_id] = generation
    return generation


def publish(root, bundle, incoming, row, generation, project):
    original = read(bundle / 'profiles.json')[row['id']]
    if digest(bundle / 'profiles.json') != generation['profiles_hash']:
        raise RuntimeError('Target source selection changed')
    if project not in generation['revisions']:
        raise RuntimeError('Project is not selected for this release')
    current, _ = published(root, row)
    baseline = original['baseline']
    if project == 'mqttsuite' and original['context']['release_project'] == 'snode.c':
        # The application must follow this target's successful library publication.
        # Allow an idempotent retry of this application's own completed publication.
        if (current.get('context', {}).get('run_id') != generation['run_id']
                or project_revision(current, 'snode.c') != int(generation['revisions']['snode.c'])
                or current.get('sources', {}).get('snode.c') != original['sources']['snode.c']):
            raise RuntimeError('Corresponding SNode.C release has not been published or was superseded')
        baseline = current
    other = 'mqttsuite' if project == 'snode.c' else 'snode.c'
    dependency_files = lambda info: {k: v for k, v in info.get('files', {}).items() if project_file(k, other)}
    if (current.get('sources', {}).get(other) != baseline.get('sources', {}).get(other)
            or dependency_files(current) != dependency_files(baseline)):
        raise RuntimeError('Superseded build: published counterpart changed')
    profile = select(bundle, row['id'], project, baseline)
    manifests = list(incoming.rglob('build.json'))
    if len(manifests) != 1:
        raise RuntimeError('A publisher must receive exactly one target artifact')
    metadata = read(manifests[0])
    if dependency_files(metadata) != dependency_files(baseline):
        raise RuntimeError('Artifact changed the published counterpart packages')
    if (metadata['revision'] != generation['revisions'][project] or metadata['sources'] != profile['sources']
            or metadata['context'] != profile['context']):
        raise RuntimeError('Artifact does not belong to this project build generation')
    if row['family'] == 'openwrt':
        expected = incoming / 'openwrt' / row['suite'] / row['arch'] / 'build.json'
    elif row['family'] == 'raspberrypi':
        expected = incoming / 'raspberrypios' / row['suite'] / row['arch'] / 'build.json'
    else:
        expected = incoming / 'linux' / row['distribution'] / row['suite'] / row['arch'] / 'build.json'
    if manifests[0] != expected:
        raise RuntimeError('Artifact belongs to a different target')
    if row['family'] == 'openwrt':
        importlib.import_module('ci.repository').publish(incoming, root, bundle)
    elif row['family'] == 'raspberrypi':
        importlib.import_module('ci.publish.apt').publish(incoming, root, bundle)
    else:
        importlib.import_module('ci.publish.linux').publish(incoming, root, bundle)
    info, directory = published(root, row)
    if 'published_at' not in info:
        info['published_at'] = datetime.now(timezone.utc).isoformat()
        manifest = root / directory / 'build.json'
        aggregate = read(manifest)
        if 'targets' in aggregate:
            aggregate['targets'][row['arch']] = info
        else:
            aggregate = info
        write(manifest, aggregate)
    shutil.copytree(ROOT / 'keys', root / 'keys', dirs_exist_ok=True)
    importlib.import_module('ci.publish.cleanup').cleanup(root, row)


def event(state, generation, row, project, status, attempt):
    if row not in generation['targets'] or project not in generation['revisions']:
        raise ValueError('Unknown build target or project')
    update(state, row, generation, project, status, attempt)
    current = state['targets'].get(f"{row['id']}/{project}", {})
    if (project == 'snode.c' and generation['context']['release_project'] == 'snode.c'
            and current.get('run_id') == generation['run_id'] and current.get('attempt') == attempt
            and current.get('status') in {'failed', 'cancelled', 'skipped', 'superseded'}):
        update(state, row, generation, 'mqttsuite', 'skipped', attempt)


def main():
    command, *args = sys.argv[1:]
    if command == 'reserve':
        reserve(Path(args[0]), os.environ['RELEASE_PROJECT'], os.environ['GITHUB_RUN_ID'])
        return
    if command == 'matrix':
        print(json.dumps({'include': targets()}))
        return
    if command == 'scope':
        row = json.loads(args[0])
        if row and row not in targets():
            raise ValueError('Unknown publication target')
        print('\n'.join(['**/build.json', '/README.md', '/docs/', '/install/', '/status.json', '/retention.json', '/status/', '/keys/']
                        + ([f'/{path}/' for path in feed_paths(row)] if row else [])))
        return
    root, bundle = (Path(p).resolve() for p in args[:2])
    state = read(root / 'status.json', dict(repository='SNodeC/Packages', branch='main', runs={}, targets={}))
    if state.get('repository') != 'SNodeC/Packages' or state['branch'] != 'main':
        raise RuntimeError('Publication destination mismatch')
    context = read(bundle / 'context.json')
    if context['destination'] != state['repository']:
        raise RuntimeError('Publication destination mismatch')
    generation = record_run(bundle, state, context)
    attempt = int(os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
    if command == 'status':
        target, project, status = args[2:5]
        if target == '-' and project == '-' and status == 'pending':
            for row in generation['targets']:
                for project in generation['revisions']:
                    event(state, generation, row, project, status, attempt)
        else:
            event(state, generation, json.loads(target), project, status, attempt)
    elif command == 'finalize':
        status = args[2]
        if status not in {'cancelled', 'failed'}:
            raise ValueError('Invalid final status')
        for key, item in list(state['targets'].items()):
            if (item['run_id'] == generation['run_id'] and item['attempt'] == attempt
                    and item['status'] not in TERMINAL):
                project = key.rsplit('/', 1)[1]
                update(state, item['target'], generation, project, status, attempt)
    elif command == 'feed':
        row, project = json.loads(args[2]), args[3]
        original_context = (bundle / 'context.json').read_bytes()
        original_sources = (bundle / 'sources.json').read_bytes()
        result, status = 0, 'published'
        try:
            publish(root, bundle, Path(args[4]).resolve(), row, generation, project)
            shutil.copy2(ROOT / 'README.md', root / 'README.md')
            shutil.copytree(ROOT / 'docs', root / 'docs', dirs_exist_ok=True)
            shutil.copytree(ROOT / 'install', root / 'install', dirs_exist_ok=True)
        except Exception as error:
            print(f'Publication rejected: {error}', file=sys.stderr)
            run('git', '-C', str(root), 'reset', '--hard', 'HEAD')
            run('git', '-C', str(root), 'clean', '-fd')
            status = 'superseded' if 'superseded' in str(error).lower() else 'failed'
            result = 1
        finally:
            (bundle / 'context.json').write_bytes(original_context)
            (bundle / 'sources.json').write_bytes(original_sources)
        print(status)
        return result
    else:
        raise ValueError(f'Unknown publication operation: {command}')
    write(root / 'status.json', state)
    render(root, state)
    return 0


if __name__ == '__main__':
    sys.exit(main())
