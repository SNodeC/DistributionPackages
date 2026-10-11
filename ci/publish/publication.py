"""Monotonic build events and serialized feed publication for Packages/main."""
from datetime import datetime, timezone
import importlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys

from ci.repository import ROOT, matrix, linux_matrix, run, select, project_file, digest, PROJECTS, REPOSITORIES, project_revision, package_version


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
    """Project recorded release and feed facts; never mutate feeds or event state."""
    colors = {'current': '#1a7f37', 'outdated': '#9a6700', 'pending': '#57606a', 'running': '#0969da',
              'publishing': '#8250df', 'published': '#1a7f37', 'failed': '#cf222e', 'cancelled': '#24292f',
              'skipped': '#9a6700', 'superseded': '#57606a', 'not-built': '#57606a'}
    badges = root / 'status/badges'
    badges.mkdir(parents=True, exist_ok=True)
    for label, color in colors.items():
        (badges / f'{label}.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14" role="img" aria-label="{label}"><circle cx="7" cy="7.8" r="6" fill="{color}"/></svg>\n')
    for obsolete in (root / 'status').glob('*.svg'):
        obsolete.unlink()
    dot = lambda label: f'<img src="badges/{label}.svg" alt="{label}" title="{label.capitalize()}" width="14" height="14" align="absmiddle">'
    stamp = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M') if value else '—'
    rows = targets()
    releases = list(dict.fromkeys((row['distribution'], row['suite']) for row in rows))
    rows.sort(key=lambda row: (list(DISTRIBUTIONS).index(row['distribution']), releases.index((row['distribution'], row['suite'])), row['arch']))
    projects, platforms, legacy, anchors = [], [], [], {}
    template = (ROOT / 'ci/templates/package-status.md').read_text()
    menu_dir = root / 'status/menu'
    menu_dir.mkdir(exist_ok=True)
    button_source = (ROOT / 'site/docs/media/menu/status.svg').read_text()
    def button(label, href):
        slug = re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')
        svg = button_source.replace('Status', label.replace('↑ ', ''))
        if label in {'Install guide', '↑ menu'}:
            transform = 'translate(112 12)' + (' rotate(-90 4.5 2)' if label == '↑ menu' else '')
            svg = svg.replace('x="66.5" y="19"', 'x="58.5" y="19"').replace('</svg>', f'<path d="M0 1.25H5.5V0L9 2L5.5 4V2.75H0Z" transform="{transform}" fill="#ffffff"/></svg>')
        (menu_dir / f'{slug}.svg').write_text(svg)
        return f'[![{label}](menu/{slug}.svg)]({href})'
    for project, config in PROJECTS.items():
        candidates = [generation for generation in state.get('runs', {}).values() if project in generation.get('revisions', {})]
        latest = max(candidates, key=lambda generation: (int(generation['revisions'][project]), generation.get('context', {}).get('captured_at', ''), generation.get('run_id', '')), default={})
        source = latest.get('sources', {}).get(project)
        tag = next((ref.removeprefix('refs/tags/') for ref in source if not ref.endswith('^{}')), None) if isinstance(source, dict) else source
        version = tag.removeprefix('v') if tag and re.fullmatch(r'v?\d+\.\d+\.\d+', tag) else None
        revision = latest.get('revisions', {}).get(project)
        release = f'{version} · r{revision}' if version and revision is not None else '—'
        navigation = ' '.join(button(label, href) for label, href in [
            ('All projects', 'README.md#page-overview'), ('Installation', '../README.md#install'),
            ('Package catalog', f'../docs/{config["package"]}-package-options.md#page-overview'),
            ('Troubleshooting', '../docs/troubleshooting.md#page-overview')] if label != 'Package catalog' or (root / href.removeprefix('../').split('#')[0]).is_file())
        sections = {}
        for row in rows:
            info, feed = published(root, row)
            available = info.get('versions', {}).get(config['package'], info.get('versions', {}).get(project))
            key = f"{row['id']}/{project}"
            item = state.get('targets', {}).get(key, {})
            record = state.get('timeline', {}).get(key, {}).get('published', {})
            same_revision = available and str(project_revision(info, project)) == str(revision)
            expected = package_version(row, version, revision) if version and revision is not None else None
            current = ((dot('current' if same_revision and available == expected else 'outdated') + ' ') if expected else '') + f'`{available}`' if available else '—'
            matching_publication = available and str(record.get('revision')) == str(project_revision(info, project))
            published_at = record.get('at') if matching_publication else None
            if not published_at and info.get('context', {}).get('build_project') == project:
                published_at = info.get('published_at')
            status = item.get('status')
            attempt = expected and revision is not None and str(item.get('revision')) == str(revision) and status in ORDER
            in_build = f'{dot(status.replace(" ", "-"))} `{expected}`' if attempt and status != 'published' else '—'
            if in_build != '—':
                log = item.get('job_url') or item.get('run_url')
            else:
                log = record.get('job_url') if matching_publication else None
                if not log and available and same_revision and status == 'published':
                    log = item.get('job_url') or item.get('run_url')
            packages = f"{row['distribution']}/pool/{row['suite']}" if row['distribution'] in {'debian', 'ubuntu', 'raspberrypios'} else f'{feed}/Packages' if row['distribution'] in {'rocky', 'fedora'} else feed
            links = ([f'[Build log]({log})'] if log else []) + [f'[Packages](../{packages}/)']
            sections.setdefault(row['distribution'], {}).setdefault(row['suite'], []).append(
                f"| `{row['arch']}` | {current} | {stamp(published_at)} | {in_build} | {' · '.join(links)} |")
        body, menu = [], []
        for distribution, releases in sections.items():
            title, guide = DISTRIBUTIONS[distribution]
            menu.append(f'**{title}** ' + ' '.join(button(suite, f'#{distribution}-{suite.replace(".", "")}') for suite in releases))
            body += [f'## {title}', button('Install guide', f'../docs/{guide}.md#page-overview')]
            for suite, lines in releases.items():
                body += [f'<a id="{distribution}-{suite.replace(".", "")}"></a>\n\n### {title} {suite}',
                         button('↑ menu', '#page-overview'),
                         '| Architecture | Available | Published (UTC) | In build | Links |\n| --- | --- | --- | --- | --- |\n' + '\n'.join(lines)]
        legend = ' · '.join(f'{dot(label)} {label.replace("-", " ").capitalize()}' for label in colors)
        page = template.replace('<!-- title -->', config['title']).replace('<!-- release -->', release).replace('<!-- navigation -->', navigation).replace('<!-- menu -->', '\n\n'.join(menu)).replace('<!-- body -->', '\n\n'.join(body)).replace('<!-- legend -->', legend)
        (root / f"status/{config['package']}.md").write_text(page)
        projects.append((config, project, release))
    for distribution, (title, guide) in DISTRIBUTIONS.items():
        selected = sorted((row for row in rows if row['distribution'] == distribution), key=lambda row: (row['suite'], row['arch']))
        suites = list(dict.fromkeys(row['suite'] for row in selected))
        architectures = list(dict.fromkeys(row['arch'] for row in selected))
        platforms.append(f"| [{title}](docs/{guide}.md#page-overview) | {', '.join(suites)} | {', '.join(architectures) if len(architectures) < 8 else str(max(sum(row['suite'] == suite for row in selected) for suite in suites)) + ' per release (names can differ)'} |")
        slug = title.lower().replace(' ', '-')
        legacy.append(f'## {title}')
        for suite in suites:
            old = suite.replace('.', ''); count = anchors.get(old, 0); anchors[old] = count + 1
            legacy.append(f'<a id="{old + ("-" + str(count) if count else "")}"></a>\n<a id="{slug}-{suite.replace(".", "")}"></a>\n\n### {title} {suite}\n\n' +
                          ' '.join(button(config['title'], f"../status/{config['package']}.md#{distribution}-{suite.replace('.', '')}").replace('(menu/', '(../status/menu/') for config in PROJECTS.values()))
    def overview(prefix):
        return '| Project | Latest release | Status |\n| --- | --- | --- |\n' + '\n'.join(
            f'| [{config["title"]}](https://github.com/SNodeC/{project}#project-overview) | {release} | [{config["title"]} status →]({prefix}{config["package"]}.md#page-overview) |' for config, project, release in projects)
    intro = '<!-- Generated by DistributionPackages; do not edit. -->\n<a id="page-overview"></a>\n\n[![Packages](../docs/media/page-banner.svg)](../README.md#project-overview)\n\n'
    (root / 'status/README.md').write_text(intro + button('Installation', '../README.md#install') + ' ' + button('Troubleshooting', '../docs/troubleshooting.md#page-overview') + '\n\n# Package status\n\n' + overview('') + '\n')
    (root / 'docs').mkdir(exist_ok=True)
    (root / 'docs/status.md').write_text(intro.replace('../docs/media/', 'media/') +
        '# Package status\n\nStatus now has [one page per project](../status/README.md#page-overview). Existing distribution and release links remain below.\n\n' + '\n\n'.join(legacy) + '\n')
    readme = root / 'README.md'
    if readme.exists():
        text = readme.read_text()
        for name, table in [('projects', overview('status/')), ('platforms', '| Distribution | Releases | Architectures |\n| --- | --- | --- |\n' + '\n'.join(platforms))]:
            text = re.sub(f'(<!-- packages:begin {name} -->).*?(<!-- packages:end {name} -->)', lambda match: match[1] + '\n' + table + '\n' + match[2], text, flags=re.S)
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
    state['targets'][key] = dict(target=row, revision=revision, attempt=attempt,
                                run_id=generation['run_id'], run_url=generation['run_url'], status=status,
                                job_url=job_url or (previous.get('job_url') if previous.get('run_id') == generation['run_id']
                                                   and previous.get('attempt') == attempt else None) or generation['run_url'])
    if status == 'published':
        current_event['published_at'] = now
        timeline['published'] = dict(revision=revision, at=now, run_id=generation['run_id'],
                                     job_url=state['targets'][key]['job_url'])
    timeline['event'] = current_event


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
    shutil.copy2(ROOT / 'keys/snodec-opkg.pub', root / 'keys/snodec-usign.pub')  # Stable legacy download URL.
    shutil.copy2(Path(os.environ.get('PACKAGE_SITE', ROOT / 'site')) / 'keys/README.md', root / 'keys/README.md')
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


def merge_readme(root, previous, remote):
    """Merge authored README text; generated blocks are rebuilt from merged state."""
    def authored(text):
        return re.sub(r'(<!-- packages:begin (projects|platforms) -->).*?(<!-- packages:end \2 -->)',
                      lambda match: match[1] + '\n' + match[3], text, flags=re.S)
    def blob(ref):
        return subprocess.check_output(['git', '-C', str(root), 'show', f'{ref}:README.md'], text=True) if run('git', '-C', str(root), 'ls-tree', ref, '--', 'README.md') else ''
    readme = root / 'README.md'
    base, theirs = blob(previous), blob(remote)
    ours = readme.read_text() if readme.exists() else ''
    if base and not theirs:
        raise RuntimeError('Remote README removed; refusing to replace authored content')
    if not any((base, theirs, ours)):
        return
    with tempfile.TemporaryDirectory() as temporary:
        paths = [Path(temporary) / name for name in ('ours', 'base', 'theirs')]
        for path, text in zip(paths, (ours, base, theirs)):
            path.write_text(authored(text))
        result = subprocess.run(['git', 'merge-file', '-p', *(str(path) for path in paths)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Conflicting authored README edits; refusing to replace them')
        readme.write_text(result.stdout)


def main():
    command, *args = sys.argv[1:]
    if command in {'render', 'merge-readme'}:
        root = Path(args[0]).resolve()
        if command == 'merge-readme':
            merge_readme(root, *args[1:])
        else:
            render(root, read(root / 'status.json', {}))
        return
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
