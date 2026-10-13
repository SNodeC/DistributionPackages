"""Monotonic build events and serialized feed publication for Packages/main."""
from datetime import datetime, timezone
import importlib.util
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
    'openwrt': ('OpenWrt', 'openwrt'), 'raspberrypios': ('Raspberry Pi OS', 'raspberry-pi-os'),
    'debian': ('Debian', 'debian'), 'ubuntu': ('Ubuntu', 'ubuntu'),
    'rocky': ('Rocky Linux', 'rocky-linux'), 'fedora': ('Fedora', 'fedora'),
}


def render(root, state):
    """Project recorded release and feed facts; never mutate feeds or event state."""
    projects = []
    for project, config in PROJECTS.items():
        candidates = [generation for generation in state.get('runs', {}).values() if project in generation.get('revisions', {})]
        latest = max(candidates, key=lambda generation: (int(generation['revisions'][project]), generation.get('context', {}).get('captured_at', ''), generation.get('run_id', '')), default={})
        source = latest.get('sources', {}).get(project)
        tag = next((ref.removeprefix('refs/tags/') for ref in source if not ref.endswith('^{}')), None) if isinstance(source, dict) else source
        version = tag.removeprefix('v') if tag and re.fullmatch(r'v?\d+\.\d+\.\d+', tag) else None
        revision = latest.get('revisions', {}).get(project)
        release = f'{version} · r{revision}' if version and revision is not None else '—'
        projects.append((config, project, release, version, revision))
    # Resolve the approved read-only presentation dependency once for this render.
    # No persisted checkout/cache, and no package or signing logic comes from it.
    with tempfile.TemporaryDirectory(prefix='snodec-navigation-') as temporary:
        control = Path(temporary) / 'control'
        subprocess.run(['git', '-c', 'http.https://github.com/.extraheader=', 'clone',
                        '--quiet', '--depth=1', '--filter=blob:none', '--sparse', '--branch', 'main',
                        'https://github.com/SNodeC/.github.git', str(control)], env=dict(PATH=os.defpath, HOME=temporary), check=True, timeout=120)
        subprocess.run(['git', '-C', str(control), 'sparse-checkout', 'set', 'tools/snodec_sync',
                        'navigation', 'brand', 'catalog.yml', '--skip-checks'], env=dict(PATH=os.defpath, HOME=temporary), check=True, timeout=120)
        environment = dict(PATH=os.defpath, HOME=temporary, PYTHONPATH=temporary)
        if importlib.util.find_spec('yaml') is None:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--no-cache-dir',
                            '--target', temporary, 'PyYAML'], env=environment, check=True, timeout=120)
        paths = ['status/README.md', *(f"status/{config['package']}.md" for config in PROJECTS.values())]
        # Isolated read-only worker: no feed paths, CI credentials or signing environment.
        worker = """import json, sys
sys.path.insert(0, sys.argv[1])
from snodec_sync.navigation import render_header
print(json.dumps({path: render_header('Packages', path) for path in json.load(sys.stdin)}))
"""
        result = subprocess.run([sys.executable, '-c', worker, str(control / 'tools')],
                                input=json.dumps(paths), text=True, capture_output=True,
                                cwd=temporary, env=environment, check=True, timeout=120)
        headers = json.loads(result.stdout)
    indicators = {
        'current': '<circle cx="7" cy="7" r="6" fill="#1a7f37"/>',
        'published': '<circle cx="7" cy="7" r="6" fill="#1a7f37"/><path d="M4 7.2l2 2 4-4.2" fill="none" stroke="white" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
        'outdated': '<circle cx="7" cy="7" r="6" fill="#9a6700"/>',
        'skipped': '<circle cx="7" cy="7" r="5.25" fill="none" stroke="#9a6700" stroke-width="1.5"/><path d="M4.5 7h5" fill="none" stroke="#9a6700" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
        'running': '<circle cx="7" cy="7" r="6" fill="#0969da"/><circle cx="7" cy="7" r="2" fill="white"/>',
        'publishing': '<circle cx="7" cy="7" r="6" fill="#8250df"/><path d="M7 4v6M4.5 6.5L7 4l2.5 2.5" fill="none" stroke="white" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
        'failed': '<circle cx="7" cy="7" r="6" fill="#cf222e"/><path d="M4.8 4.8l4.4 4.4M9.2 4.8l-4.4 4.4" fill="none" stroke="white" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
        'pending': '<circle cx="7" cy="7" r="5.25" fill="none" stroke="#848d97" stroke-width="1.5"/>',
        'superseded': '<circle cx="7" cy="7" r="5.25" fill="none" stroke="#848d97" stroke-width="1.5" stroke-dasharray="2.2 1.6"/>',
        'not-built': '<circle cx="7" cy="7" r="5.25" fill="none" stroke="#848d97" stroke-width="1.5"/><circle cx="7" cy="7" r="1.4" fill="#848d97"/>',
        'cancelled': '<circle cx="7" cy="7" r="5.25" fill="none" stroke="#848d97" stroke-width="1.5"/><path d="M3.3 10.7L10.7 3.3" fill="none" stroke="#848d97" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
    }
    badges = root / 'status/badges'
    badges.mkdir(parents=True, exist_ok=True)
    for label, body in indicators.items():
        (badges / f'{label}.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14" role="img" aria-label="{label.replace("-", " ")}"><title>{label.replace("-", " ")}</title>{body}</svg>\n')
    for obsolete in [*(root / 'status').glob('*.svg'), *(root / 'status/menu').glob('*.svg')]:
        obsolete.unlink()
    dot = lambda label: f'<img src="badges/{label}.svg" alt="{label.replace("-", " ")}" title="{label.replace("-", " ").capitalize()}" width="14" height="14" align="absmiddle">'
    stamp = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M') if value else '—'
    rows = targets()
    releases = list(dict.fromkeys((row['distribution'], row['suite']) for row in rows))
    rows.sort(key=lambda row: (list(DISTRIBUTIONS).index(row['distribution']), releases.index((row['distribution'], row['suite'])), row['arch']))
    platforms = []
    template = (ROOT / 'ci/templates/package-status.md.tmpl').read_text()
    for config, project, release, version, revision in projects:
        navigation = ' '.join(
            f'<a href="{href}"><img src="../docs/media/menu/{asset}.svg" alt="{label}"></a>' for label, asset, href in [
            ('Install', 'install', '../README.md#install'), ('Catalog', 'catalog', f'../docs/catalogs/{config["package"]}.md#page-overview'),
            ('Troubleshoot', 'troubleshoot', '../docs/troubleshooting.md#page-overview')] if label != 'Catalog' or (root / href.removeprefix('../').split('#')[0]).is_file())
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
        body, menu = [], ['<a id="distributions"></a>', '| Distribution | Jump to release |\n| --- | --- |']
        for distribution, releases in sections.items():
            title, guide = DISTRIBUTIONS[distribution]
            menu.append(f'| {title} | ' + ' · '.join(f'[{suite}](#{distribution}-{suite.replace(".", "")})' for suite in releases) + ' |')
            body += [f'## {title}', f'[{title} install guide](../docs/installation/{guide}.md#page-overview)']
            for suite, lines in releases.items():
                body += [f'<a id="{distribution}-{suite.replace(".", "")}"></a>\n\n### {title} {suite}',
                         '[↑ Distributions](#distributions)',
                         '| Architecture | Available | Published (UTC) | In build | Links |\n| --- | --- | --- | --- | --- |\n' + '\n'.join(lines)]
        legend = ' · '.join(f'{dot(label)}&nbsp;{label.replace("-", " ").capitalize().replace(" ", "&nbsp;")}' for label in indicators)
        page = template.replace('<!-- header -->', headers[f"status/{config['package']}.md"]).replace('<!-- title -->', config['title']).replace('<!-- release -->', release).replace('<!-- navigation -->', navigation).replace('<!-- menu -->', '\n\n'.join(menu[:1]) + '\n\n' + '\n'.join(menu[1:])).replace('<!-- body -->', '\n\n'.join(body)).replace('<!-- legend -->', legend)
        (root / f"status/{config['package']}.md").write_text(page)
    for distribution, (title, guide) in DISTRIBUTIONS.items():
        selected = [row for row in rows if row['distribution'] == distribution]
        suites = list(dict.fromkeys(row['suite'] for row in selected))
        architectures = list(dict.fromkeys(row['arch'] for row in selected))
        platforms.append(f"| [{title}](docs/installation/{guide}.md#page-overview) | {', '.join(suites)} | {', '.join(architectures) if len(architectures) < 8 else str(max(sum(row['suite'] == suite for row in selected) for suite in suites)) + ' per release (names can differ)'} |")
    def overview(prefix):
        return '| Project | Latest release | Status |\n| --- | --- | --- |\n' + '\n'.join(
            f'| [{config["title"]}](https://github.com/SNodeC/{project}#project-overview) | {release} | [{config["title"]} status]({prefix}{config["package"]}.md#page-overview) |' for config, project, release, *_ in projects)
    intro = '<!-- Generated by DistributionPackages; do not edit. -->\n\n'
    (root / 'status/README.md').write_text(intro + headers['status/README.md'] + '\n\n# Package status\n\n<!-- snodec:begin menu -->\n[![Install](../docs/media/menu/install.svg)](../README.md#install) [![Troubleshoot](../docs/media/menu/troubleshoot.svg)](../docs/troubleshooting.md#page-overview)\n<!-- snodec:end menu -->\n\n' + overview('') + '\n')
    (root / 'docs/status.md').unlink(missing_ok=True)
    readme = root / 'README.md'
    if readme.exists():
        text = readme.read_text()
        for name, table in [('projects', overview('status/')), ('platforms', '| Distribution guide | Releases | Architectures |\n| --- | --- | --- |\n' + '\n'.join(platforms))]:
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


def copy_site(root):
    site = Path(os.environ.get('PACKAGE_SITE', ROOT / 'site'))
    shutil.copy2(site / 'README.md', root / 'README.md')
    if (root / 'docs').exists():
        shutil.rmtree(root / 'docs')
    shutil.copytree(site / 'docs', root / 'docs')
    (root / 'keys').mkdir(exist_ok=True)
    shutil.copy2(site / 'keys/README.md', root / 'keys/README.md')


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
            copy_site(root)
            if (root / 'install').exists():
                shutil.rmtree(root / 'install')
            shutil.copytree(ROOT / 'install', root / 'install')
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
