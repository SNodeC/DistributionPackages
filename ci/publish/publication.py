"""Monotonic build events and serialized feed publication for Packages/main."""
from datetime import datetime, timezone
import copy
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys

from ci.repository import ROOT, run, select, project_file, digest, PROJECTS, REPOSITORIES, supports, package_owner, project_revision, package_version, affected, dependencies, rows, activate, ROW_PROJECTS, dependency_identity, source_commit, missing_prerequisites, binding
from ci.repository import ownership


def targets():
    return list({row['id']: row for config in PROJECTS.values() for row in rows(config)}.values())


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


TERMINAL = {'published', 'failed', 'cancelled', 'skipped', 'superseded', 'unsatisfiable'}
ORDER = {'not built': 0, 'pending': 1, 'running': 2, 'publishing': 3, **dict.fromkeys(TERMINAL, 4)}


DISTRIBUTIONS = {
    'openwrt': ('OpenWrt', 'openwrt'), 'raspberrypios': ('Raspberry Pi OS', 'raspberry-pi-os'),
    'debian': ('Debian', 'debian'), 'ubuntu': ('Ubuntu', 'ubuntu'),
    'rocky': ('Rocky Linux', 'rocky-linux'), 'fedora': ('Fedora', 'fedora'),
}


def render(root, state):
    """Project recorded release and feed facts; never mutate feeds or event state."""
    state = projection(state)
    recorded = {p: c for g in sorted(state.get('runs', {}).values(), key=lambda g: int(g['run_id']) if g['run_id'].isdigit() else 0) for p, c in g.get('context', {}).get('projects', {}).items()}
    if recorded:
        PROJECTS.clear()
        PROJECTS.update(recorded)
    projects = []
    for project, config in PROJECTS.items():
        config = config | dict(title=re.sub(r'[\r\n|`*_\[\]<>#!\\]', ' ', config['title']))
        candidates = [generation for generation in state.get('runs', {}).values() if project in generation.get('revisions', {})]
        latest = max(candidates, key=lambda generation: (int(generation['revisions'][project]), generation.get('context', {}).get('captured_at', ''), generation.get('run_id', '')), default={})
        source = latest.get('sources', {}).get(project)
        if latest.get('context', {}).get('contract') == 3:
            source = next((values[project] for values in latest.get('sources', {}).values() if project in values), None)
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
        'current': '<circle cx="7" cy="7" r="6" fill="#1a7f37"/><path d="M4 7.2l2 2 4-4.2" fill="none" stroke="white" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
        'outdated': '<circle cx="7" cy="7" r="6" fill="#9a6700"/><path d="M7 3.2V7l2.3 1.5" fill="none" stroke="white" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>',
        'skipped': '<circle cx="7" cy="7" r="5.25" fill="none" stroke="#9a6700" stroke-width="1.5"/><path d="M4.5 7h5" fill="none" stroke="#9a6700" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
        'running': '<circle cx="7" cy="7" r="6" fill="#0969da"/><circle cx="7" cy="7" r="2" fill="white"/>',
        'publishing': '<circle cx="7" cy="7" r="6" fill="#8250df"/><path d="M7 4v6M4.5 6.5L7 4l2.5 2.5" fill="none" stroke="white" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
        'failed': '<circle cx="7" cy="7" r="6" fill="#cf222e"/><path d="M4.8 4.8l4.4 4.4M9.2 4.8l-4.4 4.4" fill="none" stroke="white" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
        'pending': '<circle cx="7" cy="7" r="5.25" fill="none" stroke="#848d97" stroke-width="1.5"/>',
        'superseded': '<circle cx="7" cy="7" r="5.25" fill="none" stroke="#848d97" stroke-width="1.5" stroke-dasharray="2.2 1.6"/>',
        'not-built': '<circle cx="7" cy="7" r="5.25" fill="none" stroke="#848d97" stroke-width="1.5"/><circle cx="7" cy="7" r="1.4" fill="#848d97"/>',
        'cancelled': '<circle cx="7" cy="7" r="5.25" fill="none" stroke="#848d97" stroke-width="1.5"/><path d="M3.3 10.7L10.7 3.3" fill="none" stroke="#848d97" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
    }
    indicators['unsatisfiable'] = indicators['skipped']
    badges = root / 'status/badges'
    badges.mkdir(parents=True, exist_ok=True)
    for label, body in indicators.items():
        (badges / f'{label}.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14" role="img" aria-label="{label.replace("-", " ")}"><title>{label.replace("-", " ")}</title>{body}</svg>\n')
    for obsolete in [badges / 'published.svg', *(root / 'status').glob('*.svg'), *(root / 'status/menu').glob('*.svg')]:
        obsolete.unlink(missing_ok=True)
    dot = lambda label: f'<img src="badges/{label}.svg" alt="{label.replace("-", " ")}" title="{label.replace("-", " ").capitalize()}" width="14" height="14" align="absmiddle">'
    stamp = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M') if value else '—'
    rows = list({r['id']: r for g in state.get('runs', {}).values() for r in g.get('targets', [])}.values()) or targets()
    releases = list(dict.fromkeys((row['distribution'], row['suite']) for row in rows))
    rows.sort(key=lambda row: (list(DISTRIBUTIONS).index(row['distribution']), releases.index((row['distribution'], row['suite'])), row['arch']))
    platforms = []
    template = (ROOT / 'ci/templates/package-status.md.tmpl').read_text()
    for config, project, release, version, revision in projects:
        navigation = ' '.join(
            f'<a href="{href}"><img src="../docs/media/menu/{asset}.svg" alt="{label}"></a>' for label, asset, href in [
            ('Install', 'install', '../README.md#install'), ('Catalog', 'catalog', f'../docs/catalogs/{config["package"]}.md#banner'),
            ('Troubleshoot', 'troubleshoot', '../docs/troubleshooting.md#banner')] if label != 'Catalog' or (root / href.removeprefix('../').split('#')[0]).is_file())
        sections = {}
        for row in (r for r in rows if any(project in g.get('sources', {}).get(r['id'], {}) for g in state.get('runs', {}).values() if g.get('context', {}).get('contract') == 3) or not any(g.get('context', {}).get('contract') == 3 for g in state.get('runs', {}).values()) and supports(project, r)):
            info, feed = published(root, row)
            available = info.get('versions', {}).get(config['package'], info.get('versions', {}).get(project))
            key = f"{row['id']}/{project}"
            item = state.get('targets', {}).get(key, {})
            receipt = info.get('publications', {}).get(project, {})
            record = (dict(revision=receipt['revision'], job_url=receipt['job_url'], at=receipt['published_at']) if receipt else
                      state.get('timeline', {}).get(key, {}).get('published', {}))
            selected = max((g for g in state.get('runs', {}).values() if project in g.get('revisions', {}) and row in g.get('targets', [row])), key=lambda g: int(g['revisions'][project]), default={})
            selected_source = selected.get('sources', {}).get(row['id'], {}).get(project) if selected.get('context', {}).get('contract') == 3 else None
            selected_tag = next((k.removeprefix('refs/tags/v') for k in selected_source if not k.endswith('^{}')), None) if selected_source else version
            row_revision = selected.get('revisions', {}).get(project, revision)
            same_revision = available and str(project_revision(info, project)) == str(row_revision)
            expected = package_version(row, selected_tag, row_revision) if selected_tag and row_revision is not None else None
            current = ((dot('current' if same_revision and available == expected else 'outdated') + ' ') if expected else '') + f'`{available}`' if available else '—'
            matching_publication = available and str(record.get('revision')) == str(project_revision(info, project))
            published_at = record.get('at') if matching_publication else None
            if not published_at and info.get('context', {}).get('build_project') == project:
                published_at = info.get('published_at')
            status = item.get('status')
            attempt = expected and row_revision is not None and str(item.get('revision')) == str(row_revision) and status in ORDER
            in_build = f'{dot(status.replace(" ", "-"))} `{expected}`' if attempt and status != 'published' else '—'
            if in_build != '—':
                log = item.get('job_url')
            else:
                log = record.get('job_url') if matching_publication else None
                if not log and available and same_revision and status == 'published':
                    log = item.get('job_url')
            packages = f"{row['distribution']}/pool/{row['suite']}" if row['distribution'] in {'debian', 'ubuntu', 'raspberrypios'} else f'{feed}/Packages' if row['distribution'] in {'rocky', 'fedora'} else feed
            log = log if log and re.fullmatch(r'https://github.com/SNodeC/[A-Za-z0-9._-]+/actions/runs/[0-9]+/job/[0-9]+', log) else None
            links = ([f'[Build log]({log})'] if log else []) + [f'[Packages](../{packages}/)']
            sections.setdefault(row['distribution'], {}).setdefault(row['suite'], []).append(
                f"| `{row['arch']}` | {current} | {stamp(published_at)} | {in_build} | {' · '.join(links)} |")
        body, menu = [], ['<a id="distributions"></a>', '| Distribution | Jump to release |\n| --- | --- |']
        for distribution, releases in sections.items():
            title, guide = DISTRIBUTIONS[distribution]
            menu.append(f'| {title} | ' + ' · '.join(f'[{suite}](#{distribution}-{suite.replace(".", "")})' for suite in releases) + ' |')
            body += [f'## {title}', f'[{title} install guide](../docs/installation/{guide}.md#banner)']
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
        platforms.append(f"| [{title}](docs/installation/{guide}.md#banner) | {', '.join(suites)} | {', '.join(architectures) if len(architectures) < 8 else str(max(sum(row['suite'] == suite for row in selected) for suite in suites)) + ' per release (names can differ)'} |")
    def overview(prefix):
        return '| Project | Latest release | Status |\n| --- | --- | --- |\n' + '\n'.join(
            f'| [{config["title"]}](https://github.com/SNodeC/{project}#banner) | {release} | [{config["title"]} status]({prefix}{config["package"]}.md#banner) |' for config, project, release, *_ in projects)
    intro = '<!-- Generated by DistributionPackages; do not edit. -->\n\n'
    (root / 'status/README.md').write_text(intro + headers['status/README.md'] + '\n\n# Package status\n\n<!-- snodec:begin menu -->\n[![Install](../docs/media/menu/install.svg)](../README.md#install) [![Troubleshoot](../docs/media/menu/troubleshoot.svg)](../docs/troubleshooting.md#banner)\n<!-- snodec:end menu -->\n\n' + overview('') + '\n')
    (root / 'docs/status.md').unlink(missing_ok=True)
    readme = root / 'README.md'
    if readme.exists():
        text = readme.read_text()
        for name, table in [('projects', overview('status/')), ('platforms', '| Distribution guide | Releases | Architectures |\n| --- | --- | --- |\n' + '\n'.join(platforms))]:
            text = re.sub(f'(<!-- packages:begin {name} -->).*?(<!-- packages:end {name} -->)', lambda match: match[1] + '\n' + table + '\n' + match[2], text, flags=re.S)
        readme.write_text(text)
    return None


def migrate(state):
    """Import the drained display schema once; all new execution facts live per generation."""
    for key, item in state.pop('targets', {}).items():
        generation = state.get('runs', {}).get(item.get('run_id'))
        if generation is not None:
            generation.setdefault('nodes', {}).setdefault(key, item)
    for key, timeline in state.pop('timeline', {}).items():
        for name, record in timeline.items():
            generation = state.get('runs', {}).get(record.get('run_id'))
            if generation is not None:
                generation.setdefault('nodes', {}).setdefault(key, {})[name] = record
    return None


def projection(state):
    result = copy.deepcopy(state)
    migrate(result)
    result.update(targets={}, timeline={})
    for generation in result.get('runs', {}).values():
        for key, node in generation.get('nodes', {}).items():
            if 'status' in node:
                item = dict(node, revision=generation['revisions'][key.rsplit('/', 1)[1]], run_id=generation['run_id'])
                previous = result['targets'].get(key, {})
                if (int(item['revision']), item.get('attempt', 0)) >= (int(previous.get('revision', 0)), previous.get('attempt', 0)):
                    result['targets'][key] = item
                    result['timeline'].setdefault(key, {})['event'] = item.get('event', {})
            record = node.get('published', {})
            previous = result['timeline'].setdefault(key, {}).get('published', {})
            if record and int(record['revision']) >= int(previous.get('revision', 0)):
                result['timeline'][key]['published'] = record
    return result


def update(state, row, generation, project, status, attempt, job_url=None):
    if row not in generation.get('targets', [row]) or project not in generation['revisions']:
        raise ValueError('Unknown build target or project')
    key = f"{row['id']}/{project}"
    generation = state.setdefault('runs', {}).setdefault(generation['run_id'], generation)
    nodes = generation.setdefault('nodes', {})
    previous = nodes.get(key, {})
    if status not in ORDER:
        raise ValueError('Unknown status')
    if attempt > previous.get('attempt', -1) or (attempt == previous.get('attempt') and
            (status == 'published' and previous['status'] != 'published' or previous['status'] not in TERMINAL and ORDER[status] > ORDER[previous['status']])):
        now = os.environ.get('EVENT_TIME') or datetime.now(timezone.utc).isoformat()
        event = dict(revision=generation['revisions'][project], attempt=attempt, run_id=generation['run_id'],
                     status=status, updated_at=now, stage=os.environ.get('EVENT_STAGE', 'publication' if status == 'published' else 'build'))
        event.update({k: v for k, v in previous.get('event', {}).items() if k.endswith('_at') and k != 'updated_at'})
        if status == 'running':
            event['started_at'] = now
        if status in {'publishing', 'failed', 'cancelled'}:
            event['ended_at'] = now
        nodes[key] = previous | dict(target=row, status=status, attempt=attempt, event=event,
                                     job_url=job_url or (previous.get('job_url') if previous.get('attempt') == attempt else None))
        if status == 'published':
            event['published_at'] = now
            nodes[key]['published'] = dict(revision=generation['revisions'][project], at=now,
                                           run_id=generation['run_id'], job_url=nodes[key]['job_url'])
    return None


def reserve(root, project, run_id):
    """Applied and retried against Packages/main by the metadata writer."""
    if project not in REPOSITORIES:
        raise ValueError('Unknown release project')
    path = root / 'status.json'
    state = read(path, dict(repository='SNodeC/Packages', branch='main', counters=dict.fromkeys(REPOSITORIES, 0), runs={}, targets={}))
    allocations = state.setdefault('allocations', {})
    requests = state.setdefault('requests', {})
    requested_at = os.environ.get('RELEASE_REQUESTED_AT')
    if requested_at and (requests.get(project, {}).get('at', ''), int(requests.get(project, {}).get('run', 0))) > (requested_at, int(os.environ.get('RELEASE_RUN', 0))):
        raise ValueError('A newer explicit request already exists')
    if requested_at and requests.get(project, {}).get('run') == os.environ.get('RELEASE_RUN', '0') and requests[project].get('capture') != run_id:
        raise ValueError('This source notification already has a capture: ' + str(requests[project].get('capture')))
    selected = tuple(name for name in REPOSITORIES if any(name in affected(project, graph) for graph in ROW_PROJECTS.values()))
    if run_id not in allocations or (requested_at and run_id not in state.get('runs', {}) and int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')) > int(requests.get(project, {}).get('capture_attempt', 1))):
        for repo in selected:
            state['counters'][repo] = state['counters'].get(repo, 0) + 1
        allocations[run_id] = {repo: str(state['counters'][repo]) for repo in selected}
    if set(allocations[run_id]) != set(selected):
        raise RuntimeError('A retry cannot change its release project')
    if requested_at:
        requests[project] = dict(sha=os.environ['RELEASE_SHA'], tag=os.environ['RELEASE_TAG'], at=requested_at, run=os.environ.get('RELEASE_RUN', '0'), capture=run_id, capture_attempt=int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')), revision=allocations[run_id][project])
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
        generation = dict(revision=revisions[context['release_project']], revisions=revisions, context=context, sources=read(bundle / 'sources.json'),
                          targets=rows, profiles_hash=digest(bundle / 'profiles.json'), run_id=run_id, run_url=context['run_url'])
        state['runs'][run_id] = generation
    if state.get('requests', {}).get(context['release_project'], {}).get('capture') == run_id:
        state['requests'][context['release_project']].update(eligible=True, reason='Capture registered')
    return generation


def publish(root, bundle, incoming, row, generation, project):
    manifests = list(incoming.rglob('build.json'))
    if len(manifests) != 1:
        raise RuntimeError('A publisher must receive exactly one target artifact')
    metadata = read(manifests[0])
    current, _ = published(root, row)
    receipt = json.loads(os.environ.get('BUILD_RECEIPT', '{}'))
    if generation.get('context', {}).get('contract') == 3 and not receipt:
        raise ValueError('Publication requires an authenticated artifact receipt')
    # Validate every incoming byte before replacing retained sibling packages.
    directory = manifests[0].parent
    for name, checksum in metadata['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not (directory / path).resolve().is_relative_to(directory.resolve()) or (directory / path).is_symlink() or digest(directory / path) != checksum:
            raise RuntimeError('Artifact checksum mismatch')
    incoming_owners, current_owners = ownership(metadata), ownership(current)
    unsigned = {name: value for name, value in metadata['files'].items() if project_file(name, project, incoming_owners)}
    previous = current.get('publications', {}).get(project, {})
    identical = bool(receipt) and previous and all(previous.get(k) == v for k, v in receipt.items())
    if identical and previous['unsigned_files'] != unsigned:
        raise RuntimeError('Different package content under the same publication identity')
    if not identical:
        node = generation.get('nodes', {}).get(row['id'] + '/' + project, {})
        if receipt and (node.get('source') and node['source'] != receipt['source'] or previous.get('source', {}).get('run') == receipt['source']['run'] and previous['source']['attempt'] > receipt['source']['attempt']):
            raise RuntimeError('Superseded build attempt')
        activate(bundle, row['id'], json.loads(os.environ.get('BUILD_BASELINE', '{}')) or None, project)
        if digest(bundle / 'profiles.json') != generation['profiles_hash']:
            raise RuntimeError('Target source selection changed')
        if project not in generation['revisions']:
            raise RuntimeError('Project is not selected for this release')
        others = [repo for repo in current.get('sources', {}) if repo != project]
        # Verify dependencies against the actual build manifest, and preserve unrelated
        # products from the current feed inside this serialized publication transaction.
        binding = json.loads(os.environ.get('BUILD_BASELINE', '{}'))
        for dependency in dependencies(project):
            if (source_commit(current.get('sources', {}).get(dependency)) is None or dependency_identity(metadata, dependency) != dependency_identity(current, dependency)
                    or binding and dependency_identity(metadata, dependency) != dependency_identity(binding, dependency)):
                raise RuntimeError('Superseded build: published dependency changed')
        # The selected source and capture identity cannot be replaced by uploaded metadata.
        profile = select(bundle, row['id'], project, current)
        expected_context = dict(profile['context'])
        for key in ('source_tags', 'versions'):
            expected_context[key] = {project: profile['context'][key][project]}
        actual_context = dict(metadata['context'])
        for key in ('source_tags', 'versions'):
            actual_context[key] = {project: metadata['context'][key].get(project)}
        if (metadata['revision'] != generation['revisions'][project]
                or metadata['sources'].get(project) != profile['sources'].get(project)
                or actual_context != expected_context):
            raise RuntimeError('Artifact does not belong to this project build generation')
        if row['family'] == 'openwrt':
            expected = incoming / 'openwrt' / row['suite'] / row['arch'] / 'build.json'
        elif row['family'] == 'raspberrypi':
            expected = incoming / 'raspberrypios' / row['suite'] / row['arch'] / 'build.json'
        else:
            expected = incoming / 'linux' / row['distribution'] / row['suite'] / row['arch'] / 'build.json'
        if manifests[0] != expected:
            raise RuntimeError('Artifact belongs to a different target')
        for other in others:
            for name in list(metadata['files']):
                if project_file(name, other, incoming_owners):
                    (directory / name).unlink()
                    del metadata['files'][name]
            for name, checksum in current.get('files', {}).items():
                if project_file(name, other, current_owners):
                    relative = (Path(row['distribution']) / 'pool' / row['suite'] / name
                                if name.endswith('.deb') else Path(feed_paths(row)[0]) / name)
                    source = root / relative
                    if digest(source) != checksum:
                        raise RuntimeError('Published sibling checksum mismatch')
                    (directory / name).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, directory / name)
                    metadata['files'][name] = checksum
        metadata['packages'] = sorted([name for name in metadata.get('packages', []) if package_owner(name, incoming_owners) == project]
                                      + [name for name in current.get('packages', []) if package_owner(name, current_owners) in others])
        metadata['versions'] = {key: value for key, value in metadata['versions'].items()
                                if key in (project, PROJECTS[project]['package'])}
        metadata['versions'].update({key: value for key, value in current.get('versions', {}).items()
                                    if key not in (project, PROJECTS[project]['package'])})
        metadata.update(context=profile['context'], sources=profile['sources'])
        write(manifests[0], metadata)
        if row['family'] == 'openwrt':
            from ci.publish.openwrt import reindex
            reindex(directory, root / feed_paths(row)[0], metadata, project, current)
            write(manifests[0], metadata)
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
        if receipt:
            info, directory = published(root, row)
            info['publications'] = current.get('publications', {}) | {project: receipt | dict(
                revision=generation['revisions'][project], published_at=info['published_at'], unsigned_files=unsigned)}
            manifest = root / directory / 'build.json'
            aggregate = read(manifest)
            if 'targets' in aggregate:
                aggregate['targets'][row['arch']] = info
            else:
                aggregate = info
            write(manifest, aggregate)
    return None


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
    if (root / 'install').exists():
        shutil.rmtree(root / 'install')
    shutil.copytree(site.parent / 'install', root / 'install')
    (root / 'keys').mkdir(exist_ok=True)
    shutil.copy2(site / 'keys/README.md', root / 'keys/README.md')


def main():
    command, *args = sys.argv[1:]
    result = 0
    if command in {'render', 'project', 'merge-readme', 'reserve', 'control'}:
        root = Path(args[0]).resolve()
        if command == 'merge-readme':
            merge_readme(root, *args[1:])
        elif command in {'render', 'project'}:
            render(root, read(root / 'status.json', {}))
        elif command == 'control':
            if (os.environ.get('GITHUB_WORKFLOW_REF') != 'SNodeC/DistributionPackages/.github/workflows/control-packages.yml@refs/heads/main'
                    or os.environ.get('GITHUB_REPOSITORY') != 'SNodeC/DistributionPackages'):
                raise ValueError('Only the serialized coordinator may change admission state')
            from ci.dispatch import change
            change(root, read(Path(args[1])))
        else:
            if (os.environ.get('GITHUB_REPOSITORY') != 'SNodeC/DistributionPackages' or os.environ.get('GITHUB_WORKFLOW_REF') !=
                    'SNodeC/DistributionPackages/.github/workflows/orchestrate-packages.yml@refs/heads/main'):
                raise ValueError('Only the coordinator workflow may reserve package revisions')
            reserve(root, os.environ['RELEASE_PROJECT'], os.environ['GITHUB_RUN_ID'])
    elif command == 'matrix':
        print(json.dumps({'include': targets()}))
    elif command == 'scope':
        row = json.loads(args[0])
        print('\n'.join(['**/build.json', '/README.md', '/docs/', '/install/', '/status.json', '/retention.json', '/status/', '/keys/']
                        + ([f'/{path}/' for path in feed_paths(row)] if row else [])))
    else:
        root, bundle = (Path(p).resolve() for p in args[:2])
        state = read(root / 'status.json', dict(repository='SNodeC/Packages', branch='main', counters={}, runs={}))
        migrate(state)
        context = read(bundle / 'context.json')
        if state.get('repository') != context['destination'] or state['branch'] != 'main':
            raise RuntimeError('Publication destination mismatch')
        generation = record_run(bundle, state, context)
        attempt = int(os.environ.get('BUILD_ATTEMPT') or os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
        if command == 'status':
            target, project, status = args[2:5]
            if target == '-' and project == '-' and status == 'pending':
                for row in generation['targets']:
                    for project in (p for p in generation['revisions'] if supports(p, row, read(bundle / 'profiles.json')[row['id']]['projects'])):
                        profile = read(bundle / 'profiles.json')[row['id']]
                        missing = missing_prerequisites(project, row, profile.get('baseline', {}), generation['revisions'], profile['projects']) if context.get('contract') == 3 else []
                        error = profile.get('errors', {}).get(project)
                        update(state, row, generation, project, 'unsatisfiable' if missing or error else status, 0)
                        if error:
                            generation['nodes'][row['id'] + '/' + project].update(category='excluded', reason=error)
                        if missing:
                            generation['nodes'][row['id'] + '/' + project].update(requires=list(dependencies(project, profile['projects'])), category='blocked', dependencies=binding(profile.get('baseline', {}), dependencies(project, profile['projects'])), reason='Missing prerequisite target or publication: ' + ', '.join(missing))
            else:
                update(state, json.loads(target), generation, project, status, attempt, os.environ.get('BUILD_RUN_URL'))
            write(root / 'status.json', state)
        elif command == 'feed':
            row, project = json.loads(args[2]), args[3]
            original_context, original_sources = (bundle / 'context.json').read_bytes(), (bundle / 'sources.json').read_bytes()
            status = 'published'
            try:
                publish(root, bundle, Path(args[4]).resolve(), row, generation, project)
            except Exception as error:
                print(f'Publication rejected: {error}', file=sys.stderr)
                run('git', '-C', str(root), 'reset', '--hard', 'HEAD')
                run('git', '-C', str(root), 'clean', '-fd')
                status = 'superseded' if 'superseded' in str(error).lower() else 'failed'
                result = 1
            finally:
                (bundle / 'context.json').write_bytes(original_context)
                (bundle / 'sources.json').write_bytes(original_sources)
            if not result:
                try:
                    copy_site(root)
                except (OSError, RuntimeError) as error:
                    print(f'::warning::Guide update deferred: {error}', file=sys.stderr)
            print(status)
        else:
            raise ValueError('Unknown publication operation: ' + command)
    return result


if __name__ == '__main__':
    sys.exit(main())
