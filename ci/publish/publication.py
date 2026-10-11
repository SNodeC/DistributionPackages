"""Monotonic build events and serialized feed publication for Packages/main."""
from datetime import datetime, timezone
import importlib
import json
import os
import re
from pathlib import Path
import shutil
import sys

from ci.repository import ROOT, matrix, linux_matrix, run, select, project_file, digest, PROJECTS, REPOSITORIES, project_revision


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


DISTRIBUTIONS = {
    'openwrt': ('OpenWrt', 'openwrt'), 'raspberrypios': ('Raspberry Pi OS', 'raspberrypi'),
    'debian': ('Debian', 'debian'), 'ubuntu': ('Ubuntu', 'ubuntu'),
    'rocky': ('Rocky Linux', 'rocky'), 'fedora': ('Fedora', 'fedora'),
}


def render(root, state):
    """Render recorded facts only; authored docs, feeds and event state are never mutated."""
    badges = root / 'status/badges'
    badges.mkdir(parents=True, exist_ok=True)
    colors = {'pending': '#57606a', 'running': '#0969da', 'publishing': '#0969da', 'published': '#1a7f37',
              'failed': '#cf222e', 'cancelled': '#57606a', 'skipped': '#57606a', 'superseded': '#9a6700', 'not built': '#57606a'}
    width = max(map(len, colors)) * 7 + 16
    for label, color in colors.items():
        # Existing badge bytes/URLs stay immutable. New meaning is adjacent text, not new pipeline states.
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="{label}"><rect width="{width}" height="20" rx="3" fill="{color}"/><text x="{width / 2}" y="14" text-anchor="middle" fill="white" font-family="Verdana,sans-serif" font-size="11">{label}</text></svg>\n'
        (badges / (label.replace(' ', '-') + '.svg')).write_text(svg)
    for obsolete in (root / 'status').glob('*.svg'):
        obsolete.unlink()
    stamp = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if value else 'not recorded'
    rows = sorted(targets(), key=lambda row: (list(DISTRIBUTIONS).index(row['distribution']), row['suite'], row['arch']))
    index, projects, platforms, legacy, anchors = [], [], [], [], {}
    template = (ROOT / 'ci/templates/package-status.md').read_text()
    for project, config in PROJECTS.items():
        sections, attention, available = {}, [], 0
        for row in rows:
            info, feed = published(root, row)
            version = info.get('versions', {}).get(config['package'], info.get('versions', {}).get(project))
            available += bool(version)
            item = state.get('targets', {}).get(f"{row['id']}/{project}", {})
            status = item.get('status', 'published' if version else 'not built')
            record = state.get('timeline', {}).get(f"{row['id']}/{project}", {})
            event = record.get('event', {})
            if any(event.get(key) != item.get(key) for key in ('revision', 'attempt', 'run_id', 'status')):
                event = {}  # Old captured writers cannot attach stale metadata to a newer state.
            dependencies = [dep for dep in config['depends_on']
                            if state.get('targets', {}).get(f"{row['id']}/{dep}", {}).get('status') != 'published']
            waiting = dependencies and status in {'pending', 'skipped'} and all(
                state.get('targets', {}).get(f"{row['id']}/{dep}", {}).get('status', 'pending') not in TERMINAL for dep in dependencies)
            label = 'Waiting for ' + ', '.join(PROJECTS[dep]['title'] for dep in dependencies) if waiting else {
                'running': 'Building', 'publishing': 'Built · awaiting signed publication',
                'published': 'Published', 'failed': 'Publication failed' if event.get('stage') == 'publication' else
                'Build failed' if event.get('stage') == 'build' else 'Failed · stage not recorded',
                'pending': 'Queued', 'not built': 'Not built',
            }.get(status, status.capitalize())
            if status == 'skipped' and dependencies and not waiting:
                label += ' · ' + ', '.join(f"{PROJECTS[dep]['title']}: {state.get('targets', {}).get(row['id']+'/'+dep, {}).get('status', 'not built')}" for dep in dependencies)
            badge = f"![{status}](badges/{status.replace(' ', '-')}.svg)"
            generation = state.get('runs', {}).get(item.get('run_id'), {})
            tag = generation.get('sources', {}).get(project)
            tag = next((ref.removeprefix('refs/tags/') for ref in tag if not ref.endswith('^{}')), None) if isinstance(tag, dict) else tag
            attempted = f"Source: \x60{tag}\x60 · " if tag else ''
            attempted += f"r{item['revision']} · attempt {item.get('attempt', 0)}" if item else 'No attempt recorded'
            captured = generation.get('context', {}).get('captured_at')
            stamp_key = {'running': 'started_at', 'publishing': 'ended_at', 'published': 'published_at'}.get(status, 'updated_at')
            stamp_label = {'running': 'Started', 'publishing': 'Built', 'published': 'Published'}.get(status, 'Changed')
            attempt = f"{badge}<br>{label}<br>{attempted}<br>{stamp_label}: {stamp(event.get(stamp_key))}"
            attempt += f"<br>Captured: {stamp(captured)}"
            published_at = record.get('published', {}).get('at') if str(record.get('published', {}).get('revision')) == str(project_revision(info, project)) else None
            if not published_at and info.get('context', {}).get('build_project') == project:
                published_at = info.get('published_at')
            available_capture = state.get('runs', {}).get(record.get('published', {}).get('run_id'), {}).get('context', {}).get('captured_at') if published_at and str(record.get('published', {}).get('revision')) == str(project_revision(info, project)) else None
            if not available_capture and info.get('context', {}).get('build_project') == project:
                available_capture = info.get('context', {}).get('captured_at')
            current = f"\x60{version}\x60<br>Captured: {stamp(available_capture)}<br>Published: {stamp(published_at)}" if version else '—'
            packages = f"{row['distribution']}/pool/{row['suite']}" if row['distribution'] in {'debian', 'ubuntu', 'raspberrypios'} else f'{feed}/Packages' if row['distribution'] in {'rocky', 'fedora'} else feed
            links = [f'[Files](../{packages}/)', f'[Record](../{feed}/build.json)'] if info else []
            if item.get('job_url') or item.get('run_url'):
                links.insert(0, f"[Run]({item.get('job_url') or item['run_url']})")
            sections.setdefault(row['distribution'], {}).setdefault(row['suite'], []).append(
                f"| \x60{row['arch']}\x60 | {current} | {attempt} | {' · '.join(links) or '—'} |")
            if status != 'published':
                attention.append(f"- [{row['distribution']} {row['suite']} / \x60{row['arch']}\x60](#{row['distribution']}-{row['suite'].replace('.', '')}): {label}")
        body = ['## Needs attention', '\n'.join(attention) or 'No unfinished or unsuccessful attempts recorded.']
        for distribution, releases in sections.items():
            title, guide = DISTRIBUTIONS[distribution]
            body += [f'## {title}', f'[Installation guide](../docs/{guide}.md#page-overview)']
            for suite, lines in releases.items():
                body += [f'<a id="{distribution}-{suite.replace(".", "")}"></a>\n\n### {title} {suite}',
                         '| Architecture | Available | Latest attempt | Links |\n| --- | --- | --- | --- |\n' + '\n'.join(lines)]
        page = template.replace('<!-- title -->', config['title']).replace('<!-- body -->', '\n\n'.join(body))
        (root / f"status/{config['package']}.md").write_text(page)
        link = f"[{config['title']}]({config['package']}.md#page-overview)"
        index.append(f"- {link}: {available} / {len(rows)} targets have available packages; attention: {len(attention)} · [Package catalog](../docs/{config['package']}-package-options.md#page-overview).")
        projects.append(f"| [{config['title']}](https://github.com/SNodeC/{project}#project-overview) | [Packages](docs/{config['package']}-package-options.md#page-overview) | [Status](status/{config['package']}.md#page-overview) | {available} / {len(rows)} |")
    for distribution, (title, guide) in DISTRIBUTIONS.items():
        selected = [row for row in rows if row['distribution'] == distribution]
        suites = list(dict.fromkeys(row['suite'] for row in selected))
        architectures = list(dict.fromkeys(row['arch'] for row in selected))
        platforms.append(f"| [{title}](docs/{guide}.md#page-overview) | {', '.join(suites)} | {', '.join(architectures) if len(architectures) < 8 else str(max(sum(row['suite'] == suite for row in selected) for suite in suites)) + ' per release (names can differ)'} |")
        slug = title.lower().replace(' ', '-')
        legacy.append(f'## {title}')
        for suite in suites:
            old = suite.replace('.', ''); count = anchors.get(old, 0); anchors[old] = count + 1
            legacy.append(f'<a id="{old + ("-" + str(count) if count else "")}"></a>\n<a id="{slug}-{suite.replace(".", "")}"></a>\n\n### {title} {suite}\n\n' +
                          ' · '.join(f"[{config['title']}](../status/{config['package']}.md#{distribution}-{suite.replace('.', '')})" for config in PROJECTS.values()))
    intro = '<!-- Generated by DistributionPackages; do not edit. -->\n<a id="page-overview"></a>\n\n[![Packages](../docs/media/page-banner.svg)](../README.md#project-overview)\n\n'
    (root / 'status/README.md').write_text(intro + '# Package status\n\n' + '\n'.join(index) +
                                         '\n\nAvailable packages and the latest attempt are separate facts. Open a project for distribution details.\n')
    (root / 'docs').mkdir(exist_ok=True)
    (root / 'docs/status.md').write_text(intro.replace('../docs/media/', 'media/') +
        '# Package status\n\nStatus now has [one page per project](../status/README.md#page-overview). Existing distribution and release links remain below.\n\n' + '\n\n'.join(legacy) + '\n')
    readme = root / 'README.md'
    if readme.exists():
        text = readme.read_text()
        for name, table in [('projects', '| Project | Package catalog | Availability and builds | Available targets |\n| --- | --- | --- | --- |\n' + '\n'.join(projects)),
                            ('platforms', '| Distribution | Releases | Architectures |\n| --- | --- | --- |\n' + '\n'.join(platforms))]:
            text = re.sub(f'(<!-- packages:begin {name} -->).*?(<!-- packages:end {name} -->)',
                          lambda match: match[1] + '\n' + table + '\n' + match[2], text, flags=re.S)
        readme.write_text(text)


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
    timeline = state.setdefault('timeline', {}).setdefault(key, {})
    previous_event = timeline.get('event', {})
    identity = dict(revision=revision, attempt=attempt, run_id=generation['run_id'])
    current_event = dict(previous_event) if all(previous_event.get(k) == v for k, v in identity.items()) else identity
    now = os.environ.get('EVENT_TIME') or datetime.now(timezone.utc).isoformat()
    current_event.update(status=status, updated_at=now, stage=os.environ.get('EVENT_STAGE') or
                         ('publication' if status == 'published' or (incoming == existing and previous.get('status') == 'publishing') else 'build'))
    if status == 'running':
        current_event['started_at'] = now
    if status in {'publishing', 'failed', 'cancelled'}:
        current_event['ended_at'] = now
    if status == 'published':
        current_event['published_at'] = now
        timeline['published'] = dict(revision=revision, at=now, run_id=generation['run_id'])
    timeline['event'] = current_event
    state['targets'][key] = dict(target=row, revision=revision, attempt=attempt,
                                run_id=generation['run_id'], run_url=generation['run_url'], status=status,
                                job_url=job_url or (previous.get('job_url') if previous.get('run_id') == generation['run_id']
                                                   and previous.get('attempt') == attempt else None) or generation['run_url'])


def reserve(root, project, run_id):
    """Applied and retried against Packages/main by the metadata writer."""
    if project not in REPOSITORIES:
        raise ValueError('Unknown release project')
    path = root / 'status.json'
    state = read(path, dict(repository='SNodeC/Packages', branch='main', counters=dict.fromkeys(REPOSITORIES, 0), runs={}, targets={}))
    allocations = state.setdefault('allocations', {})
    selected = REPOSITORIES if project == 'snode.c' else (project,)
    if run_id not in allocations:
        for repo in selected:
            state['counters'][repo] += 1
        allocations[run_id] = {repo: str(state['counters'][repo]) for repo in selected}
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
    update(state, row, generation, project, status, attempt, os.environ.get('BUILD_RUN_URL'))
    current = state['targets'].get(f"{row['id']}/{project}", {})
    if (project == 'snode.c' and generation['context']['release_project'] == 'snode.c'
            and current.get('run_id') == generation['run_id'] and current.get('attempt') == attempt
            and current.get('status') in {'failed', 'cancelled', 'skipped', 'superseded'}):
        # No application job has run yet. Its own attempt 1 supersedes this dependency placeholder.
        update(state, row, generation, 'mqttsuite', 'skipped', 0)


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
    state = read(root / 'status.json', dict(repository='SNodeC/Packages', branch='main', counters=dict.fromkeys(REPOSITORIES, 0), runs={}, targets={}))
    if state.get('repository') != 'SNodeC/Packages' or state['branch'] != 'main':
        raise RuntimeError('Publication destination mismatch')
    context = read(bundle / 'context.json')
    if context['destination'] != state['repository']:
        raise RuntimeError('Publication destination mismatch')
    generation = record_run(bundle, state, context)
    attempt = int(os.environ.get('BUILD_ATTEMPT') or os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
    if command == 'status':
        target, project, status = args[2:5]
        if target == '-' and project == '-' and status == 'pending':
            for row in generation['targets']:
                for project in generation['revisions']:
                    event(state, generation, row, project, status,
                          attempt if project == context['release_project'] else 0)
        else:
            event(state, generation, json.loads(target), project, status, attempt)
    elif command == 'finalize':
        status = args[2]
        if status not in {'cancelled', 'failed'}:
            raise ValueError('Invalid final status')
        for key, item in list(state['targets'].items()):
            if (item['run_id'] == generation['run_id'] and item['attempt'] in {0, attempt}
                    and item['status'] not in TERMINAL
                    and (not os.environ.get('BUILD_PROJECT') or (key.endswith('/' + os.environ['BUILD_PROJECT'])
                         and item['status'] != 'publishing'
                         and os.environ.get('TARGET_ID', '-') in {'-', item['target']['id']}))):
                project = key.rsplit('/', 1)[1]
                event(state, generation, item['target'], project, status, attempt)
    elif command == 'feed':
        row, project = json.loads(args[2]), args[3]
        original_context = (bundle / 'context.json').read_bytes()
        original_sources = (bundle / 'sources.json').read_bytes()
        result, status = 0, 'published'
        try:
            previous = state['targets'].get(f"{row['id']}/{project}", {})
            if (int(generation['revisions'][project]), attempt) < (int(previous.get('revision', 0)), previous.get('attempt', 0)):
                raise RuntimeError('Superseded build attempt')
            if (previous.get('status') == 'published' and previous.get('run_id') == generation['run_id']
                    and previous.get('attempt') == attempt and os.environ.get('BUILD_RUN_URL')
                    and previous.get('job_url') == os.environ['BUILD_RUN_URL']):
                print('published')  # This immutable upstream artifact was already committed.
                return 0
            publish(root, bundle, Path(args[4]).resolve(), row, generation, project)
            site = Path(os.environ.get('PACKAGE_SITE', ROOT / 'site'))
            shutil.copy2(site / 'README.md', root / 'README.md')
            for directory in ('docs', 'install'):
                if (root / directory).exists():
                    shutil.rmtree(root / directory)
                shutil.copytree((site if directory == 'docs' else ROOT) / directory, root / directory)
            render(root, state)
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
