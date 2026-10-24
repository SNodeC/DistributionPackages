"""Monotonic build events and serialized feed publication for Packages/main."""
from datetime import datetime, timezone
from graphlib import TopologicalSorter
from html import escape
import copy
import importlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys

from ci.repository import ROOT, run, select, project_file, digest, PROJECTS, REPOSITORIES, supports, package_owner, project_revision, package_version, affected, dependencies, rows, activate, ROW_PROJECTS, dependency_identity, source_commit, missing_prerequisites, binding
from ci.repository import ownership, COORDINATOR, OWNER, FEED, FEED_BRANCH, source_tag, version, release_view, generation_tag, work_index, cascade_blockers
from ci.repository import requested_projects, package_metadata, validate_package, validate_projects, capture_inputs, recipe_commit


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


def row_activity(row, info, state):
    """Explain recorded highest-version work through immediate prerequisite pages."""
    graph, activity = state['projects'], {}
    for project in TopologicalSorter({p: c['depends_on'] for p, c in graph.items()}).static_order():
        item = state['targets'].get(row['id'] + '/' + project, {})
        own = release_view(info, project, state['latest'].get(project, {}).get('tag'))
        available = own.get('versions', {}).get(project)
        current = available and str(project_revision(own, project)) == str(
            item.get('revision', state['latest'].get(project, {}).get('revision')))
        status = item.get('status') if not current else None
        status = status if status in ORDER and status != 'published' else None if available else 'not built'
        held = []
        for capture, generation in state.get('runs', {}).items():
            root = generation.get('context', {}).get('release_project')
            node = generation.get('nodes', {}).get(row['id'] + '/' + project, {})
            source = str(node.get('source', {}).get('run'))
            reserved = state.get('allocations', {}).get(source, {}).get(project)
            if (source not in state.get('runs', {}) and project not in generation['revisions'] and node and root
                    and release_view(info, root).get('publications', {}).get(root, {}).get('capture') == capture
                    and node.get('status') not in {'published', 'superseded'}
                    and not (current and reserved is None and node.get('status') in TERMINAL
                             and node.get('dependencies') is not None and node['dependencies'] == item.get('dependencies'))
                    and (not current or reserved is None or int(reserved) > project_revision(own, project))):
                held.append(node)
        capture_node = held[-1] if held and status in {None, 'not built'} else {}
        status = capture_node.get('status', status)
        cause = item.get('cause', state.get('runs', {}).get(item.get('run_id'), {}).get('context', {}).get('cause', 'release'))
        waiting = [p for p in graph.get(project, {}).get('depends_on', []) if activity[p]['status'] not in {None, 'not built'}]
        failed = [p for p in waiting if activity[p]['status'] in {'failed', 'cancelled', 'skipped', 'unsatisfiable', 'blocked'}]
        if waiting and (status in {None, 'not built'} or status == 'pending' and (capture_node or cause == 'dependent')):
            status = 'blocked' if failed else 'waiting'
        activity[project] = dict(status=status, prerequisites=failed if status == 'blocked' else waiting if status == 'waiting' else [],
                                 capture=bool(capture_node), current=bool(current))
    return activity


def render(root, state):
    """Project recorded release and feed facts; never mutate feeds or event state."""
    state = projection(state)
    recorded = state.get('projects', {})
    projects = []
    for project, config in recorded.items():
        config = config | dict(title=re.sub(r'[\r\n|`*_\[\]<>#!\\]', ' ', config['title']))
        item = state['latest'][project]
        tag, revision = item['tag'], item['revision']
        release = tag[1:]
        projects.append((config, project, release, tag[1:], revision))
    headers = {path: '<a id="banner"></a>' for path in ['status/README.md',
               *(f"status/{config["package"]}.md" for config in recorded.values())]}
    indicators = {
        'waiting': '<circle cx="7" cy="7" r="6" fill="#9a6700"/><path d="M7 3.2V7l2.3 1.5" fill="none" '
                   'stroke="white" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>',
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
    indicators['blocked'] = indicators['failed']
    badges = root / 'status/badges'
    badges.mkdir(parents=True, exist_ok=True)
    for label, body in indicators.items():
        (badges / f'{label}.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14" role="img" aria-label="{label.replace("-", " ")}"><title>{label.replace("-", " ")}</title>{body}</svg>\n')
    for obsolete in [*(badges / (name + '.svg') for name in ['published', 'current', 'outdated']),
                     *(root / 'status').glob('*.svg'), *(root / 'status/menu').glob('*.svg')]:
        obsolete.unlink(missing_ok=True)
    dot = lambda label: f'<img src="badges/{label}.svg" alt="{label.replace("-", " ")}" title="{label.replace("-", " ").capitalize()}" width="14" height="14" align="absmiddle">'
    stamp = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M') if value else '—'
    target_rows = list({r['id']: r for c in recorded.values() for r in rows(c)}.values())
    releases = list(dict.fromkeys((row['distribution'], row['suite']) for row in target_rows))
    target_rows.sort(key=lambda row: (list(DISTRIBUTIONS).index(row['distribution']), releases.index((row['distribution'], row['suite'])), row['arch']))
    activity = {row['id']: row_activity(row, published(root, row)[0], state) for row in target_rows}
    platforms = []
    template = (ROOT / 'ci/templates/package-status.md.tmpl').read_text()
    for config, project, release, version, revision in projects:
        navigation = ' '.join(
            f'<a href="{href}"><img src="../docs/media/menu/{asset}.svg" alt="{label}"></a>' for label, asset, href in [
            ('Install', 'install', '../README.md#install'), ('Catalog', 'catalog', f'../docs/catalogs/{config["package"]}.md#banner'),
            ('Troubleshoot', 'troubleshoot', '../docs/troubleshooting.md#banner')] if label != 'Catalog' or (root / href.removeprefix('../').split('#')[0]).is_file())
        sections = {}
        for row in (r for r in target_rows if supports(project, r, {project: config})):
            info, feed = published(root, row)
            info = release_view(info, project, 'v' + version)
            available = info.get('versions', {}).get(project)
            key = f"{row['id']}/{project}"
            item = state.get('targets', {}).get(key, {})
            receipt = info.get('publications', {}).get(project, {})
            record = (dict(revision=receipt['revision'], job_url=receipt['job_url'], at=receipt['published_at']) if receipt else
                      state.get('timeline', {}).get(key, {}).get('published', {}))
            selected_tag = version
            row_revision = item.get('revision', revision)
            detail = activity[row['id']][project]
            same_revision = detail['current']
            expected = package_version(row, selected_tag, row_revision) if selected_tag and row_revision is not None else None
            current = f'<code>{escape(available)}</code>' if available else '—'
            matching_publication = available and str(record.get('revision')) == str(project_revision(info, project))
            published_at = record.get('at') if matching_publication else None
            if not published_at and info.get('context', {}).get('build_project') == project:
                published_at = info.get('published_at')
            status = detail['status']
            labels = []
            for dependency in detail['prerequisites']:
                config_dependency = recorded.get(dependency)
                label = escape(config_dependency['title'] if config_dependency else dependency)
                if config_dependency:
                    label = f'<a href="{escape(config_dependency["package"])}.md#banner">{label}</a>'
                if status == 'blocked' and activity[row['id']][dependency]['status'] in TERMINAL:
                    label += ' ' + activity[row['id']][dependency]['status']
                labels.append(label)
            label = ('Waiting for ' if status == 'waiting' else 'Blocked: ') + ', '.join(labels) if labels else (
                'Building' if status == 'running' else status.capitalize() if status else '')
            if detail['capture'] and not labels:
                label += ' capture'
            elif expected and status and not labels and status != 'not built':
                label += f' <code>{escape(expected)}</code>'
            in_build = f'{dot(status.replace(" ", "-"))} {label}' if status else '—'
            if status and not detail['prerequisites'] and not detail['capture']:
                log = item.get('job_url')
            else:
                log = record.get('job_url') if matching_publication else None
                if not log and available and same_revision and item.get('status') == 'published':
                    log = item.get('job_url')
            packages = f"{row['distribution']}/pool/{row['suite']}" if row['distribution'] in {'debian', 'ubuntu', 'raspberrypios'} else f'{feed}/Packages' if row['distribution'] in {'rocky', 'fedora'} else feed
            log = log if log and re.fullmatch(rf'https://github.com/{re.escape(OWNER)}/[A-Za-z0-9._-]+/actions/runs/[0-9]+/job/[0-9]+', log) else None
            links = ([f'<a href="{escape(log)}">Build log</a>'] if log else []) + [f'<a href="../{escape(packages)}/">Packages</a>']
            sections.setdefault(row['distribution'], {}).setdefault(row['suite'], []).append(
                '<tr>' + ''.join(f'<td align="{"center" if cell == "—" else "left"}">{cell}</td>' for cell in
                    [f'<code>{escape(row["arch"])}</code>', current, stamp(published_at), in_build, ' · '.join(links)]) + '</tr>')
        body, menu = [], ['<a id="distributions"></a>', '| Distribution | Jump to release |\n| --- | --- |']
        for distribution, releases in sections.items():
            title, guide = DISTRIBUTIONS[distribution]
            menu.append(f'| {title} | ' + ' · '.join(f'[{suite}](#{distribution}-{suite.replace(".", "")})' for suite in releases) + ' |')
            body += [f'## {title}', f'[{title} install guide](../docs/installation/{guide}.md#banner)']
            for suite, lines in releases.items():
                body += [f'<a id="{distribution}-{suite.replace(".", "")}"></a>\n\n### {title} {suite}',
                         '[↑ Distributions](#distributions)',
                         '<table>\n<thead><tr>' + ''.join(f'<th>{label}</th>' for label in
                             ['Architecture', 'Available', 'Published (UTC)', 'In build', 'Links']) +
                         '</tr></thead>\n<tbody>\n' + '\n'.join(lines) + '\n</tbody>\n</table>']
        legend = ' · '.join(f'{dot(label)}&nbsp;{label.replace("-", " ").capitalize().replace(" ", "&nbsp;")}' for label in indicators)
        page = template.replace('<!-- header -->', headers[f"status/{config['package']}.md"]).replace('<!-- title -->', config['title']).replace('<!-- release -->', release).replace('<!-- navigation -->', navigation).replace('<!-- menu -->', '\n\n'.join(menu[:1]) + '\n\n' + '\n'.join(menu[1:])).replace('<!-- body -->', '\n\n'.join(body)).replace('<!-- legend -->', legend)
        (root / f"status/{config['package']}.md").write_text(page)
    for distribution, (title, guide) in DISTRIBUTIONS.items():
        selected = [row for row in target_rows if row['distribution'] == distribution]
        suites = list(dict.fromkeys(row['suite'] for row in selected))
        architectures = list(dict.fromkeys(row['arch'] for row in selected))
        if selected:
            label = ', '.join(architectures) if len(architectures) < 8 else (
                str(max(sum(row['suite'] == suite for row in selected) for suite in suites)) + ' per release (names can differ)')
            platforms.append(f"| [{title}](docs/installation/{guide}.md#banner) | {', '.join(suites)} | {label} |")
    def overview(prefix):
        return '| Project | Latest release | Status |\n| --- | --- | --- |\n' + '\n'.join(
            f'| [{config["title"]}](https://github.com/{OWNER}/{project}#banner) | {release} | '
            f'[{config["title"]} status]({prefix}{config["package"]}.md#banner) |' for config, project, release, *_ in projects)
    intro = '<!-- Generated by package CI; do not edit. -->\n\n'
    (root / 'status/README.md').write_text(intro + headers['status/README.md'] +
        '\n\n# Package status\n\n<!-- packages:begin menu -->\n'
        '[![Install](../docs/media/menu/install.svg)](../README.md#install) '
        '[![Troubleshoot](../docs/media/menu/troubleshoot.svg)](../docs/troubleshooting.md#banner)\n'
        '<!-- packages:end menu -->\n\n' + overview('') + '\n')
    (root / 'docs/status.md').unlink(missing_ok=True)
    readme = root / 'README.md'
    if readme.exists():
        tables = [('projects', overview('status/')),
                  ('platforms', '| Distribution guide | Releases | Architectures |\n| --- | --- | --- |\n' + '\n'.join(platforms))]
        generated = ''.join(f'<!-- packages:begin {name} -->\n{table}\n<!-- packages:end {name} -->'
                            for name, table in tables)
        readme.write_text(readme_blocks(readme.read_text(), generated))
    return None


def projection(state):
    result = copy.deepcopy(state)
    result.update(targets={}, timeline={}, projects={}, latest={})
    generations = list(result.get('runs', {}).values())
    for project, requests in result.get('requests', {}).items():
        for tag, request in requests.items():
            if 'definition' in request and request['capture'] not in result.get('runs', {}):
                config = request['definition']
                generations.append(dict(run_id=request['capture'], revisions={project: request['revision']},
                    context=dict(tag=tag, release_project=project, projects={project: config}), targets=rows(config), sources={},
                    nodes={r['id'] + '/' + project: dict(status='pending' if request.get('eligible', True) else 'failed',
                           reason=request.get('reason', 'Capture pending')) for r in rows(config)}))
    for generation in generations:
        for project, revision in generation['revisions'].items():
            tag = generation_tag(generation, project)
            previous = result['latest'].get(project, {})
            if tag and (version(tag), int(revision)) >= (version(previous.get('tag', 'v0.0.0')), int(previous.get('revision', 0))):
                result['latest'][project] = dict(tag=tag, revision=revision)
                if project in generation.get('context', {}).get('projects', {}):
                    result['projects'][project] = generation['context']['projects'][project]
        for key, node in generation.get('nodes', {}).items():
            project = key.rsplit('/', 1)[1]
            tag = generation_tag(generation, project, key.rsplit('/', 1)[0])
            previous = result['targets'].get(key, {})
            timeline = result['timeline'].setdefault(key, {})
            recorded = timeline.get('published', {})
            if tag and node.get('published') and (version(tag), int(node['published']['revision'])) >= (
                    version(recorded.get('tag', 'v0.0.0')), int(recorded.get('revision', 0))):
                timeline['published'] = dict(node['published'], tag=tag)
            if project in generation['revisions'] and tag and (version(tag), int(generation['revisions'][project]), node.get('attempt', 0)) >= (
                    version(previous.get('tag', 'v0.0.0')), int(previous.get('revision', 0)), previous.get('attempt', 0)):
                item = dict(node, tag=tag, revision=generation['revisions'][project], run_id=generation['run_id'])
                result['targets'][key] = item
                timeline['event'] = item.get('event', {})
    result['targets'] = {k: n for k, n in result['targets'].items() if n['tag'] == result['latest'][k.rsplit('/', 1)[1]]['tag']}
    result['timeline'] = {k: v | dict(published=v.get('published', {}) if v.get('published', {}).get('tag') == result['targets'][k]['tag'] else {})
                          for k, v in result['timeline'].items() if k in result['targets']}
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


def shared_revision(state, info, project, target, tag, inputs, run_id):
    work, captures = work_index(state)
    links = [(key.rsplit('/', 1)[0], node['source'], node['status'])
             for (_, key), node in captures.items() if key.rsplit('/', 1)[1] == project
             and str(node.get('source', {}).get('run')) in state['allocations']
             and str(node['source']['run']) != run_id]
    numbers = [(row, source.get('inputs'), int(state['allocations'][str(source['run'])][project]),
                status not in TERMINAL or str(source['run']) in state['runs']) for row, source, status in links]
    claimed = max([project_revision(release_view(info, project, tag), project),
                   work.get((target, project, tag), (0,))[0],
                   int(state.get('requests', {}).get(project, {}).get(tag, {}).get('revision', 0)),
                   *(number for row, _, number, _ in numbers if row == target)])
    candidate = max((number for _, value, number, donor in numbers if donor and value == inputs), default=0)
    return str(candidate) if candidate > claimed else None


def reserve(root, project, run_id):
    """Applied and retried against Packages/main by the metadata writer."""
    if project not in REPOSITORIES:
        raise ValueError('Unknown release project')
    path = root / 'status.json'
    state = read(path, dict(repository=FEED, branch=FEED_BRANCH, counters=dict.fromkeys(REPOSITORIES, 0), runs={}, targets={}))
    state.setdefault('runs', {})
    allocations = state.setdefault('allocations', {})
    requests = state.setdefault('requests', {})
    requested_at = os.environ.get('RELEASE_REQUESTED_AT')
    tag = os.environ.get('RELEASE_TAG', '')
    previous = requests.get(project, {}).get(tag, {})
    if requested_at and (previous.get('at', ''), int(previous.get('run', 0))) > (requested_at, int(os.environ.get('RELEASE_RUN', 0))):
        raise ValueError('A newer explicit request already exists')
    if requested_at and previous.get('run') == os.environ.get('RELEASE_RUN', '0') and previous.get('capture') != run_id:
        raise ValueError('This source notification already has a capture: ' + str(previous.get('capture')))
    parent = json.loads(os.environ.get('RELEASE_PARENT') or '{}')
    if parent:
        node = state['runs'][parent['capture']]['nodes'][parent['target'] + '/' + project]
        if node['request'] != parent or node.get('source', {}).get('run', int(run_id)) != int(run_id):
            raise ValueError('Cascade capture does not own the admitted intent')
        row = next(r for r in rows(PROJECTS[project]) if r['id'] == parent['target'])
        info, _, _, inputs = capture_inputs(root, row, project, tag, os.environ['RELEASE_SHA'], recipe_commit())
        if run_id in allocations and node.get('source', {}).get('inputs') != inputs:
            raise RuntimeError('Capture inputs changed or unavailable after reservation; retry the node for a fresh capture')
        node['source'] = dict(run=int(run_id), attempt=int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')), inputs=inputs)
    if (run_id not in allocations or requested_at and run_id not in state.get('runs', {})
            and int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')) > int(previous.get('capture_attempt', 1))):
        shared = shared_revision(state, info, project, row['id'], tag, inputs, run_id) if parent else None
        if shared is None:
            state.setdefault('counters', {})[project] = state.get('counters', {}).get(project, 0) + 1
        allocations[run_id] = {project: shared or str(state['counters'][project])}
    if set(allocations[run_id]) != {project}:
        raise RuntimeError('A retry cannot change its release project')
    if requested_at:
        requests.setdefault(project, {})[tag] = dict(
            definition=PROJECTS[project], sha=os.environ['RELEASE_SHA'], tag=tag,
            at=requested_at, run=os.environ.get('RELEASE_RUN', '0'),
            capture=run_id, capture_attempt=int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')), revision=allocations[run_id][project])
        validate_projects(requested_projects(requests))
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
    request = state.get('requests', {}).get(context['release_project'], {}).get(context.get('tag'), {})
    if request.get('capture') == run_id:
        request.update(eligible=True, reason='Capture registered')
    return generation


def publish(root, bundle, incoming, row, generation, project, state=None):
    manifests = list(incoming.rglob('build.json'))
    if len(manifests) != 1:
        raise RuntimeError('A publisher must receive exactly one target artifact')
    metadata = read(manifests[0])
    current, _ = published(root, row)
    receipt = json.loads(os.environ.get('BUILD_RECEIPT', '{}'))
    if not receipt:
        raise ValueError('Publication requires an authenticated artifact receipt')
    # Validate every incoming byte before replacing retained sibling packages.
    directory = manifests[0].parent
    for name, checksum in metadata['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not (directory / path).resolve().is_relative_to(directory.resolve()) or (directory / path).is_symlink() or digest(directory / path) != checksum:
            raise RuntimeError('Artifact checksum mismatch')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != set(metadata['files']) | {'build.json'}:
        raise RuntimeError('Artifact contains undeclared files')
    incoming_owners, current_owners = ownership(dict(sources={project: metadata['sources'].get(project)})), ownership(current)
    unsigned = {name: value for name, value in metadata['files'].items() if project_file(name, project, current_owners | incoming_owners)}
    tag = source_tag(metadata, project)
    previous = release_view(current, project, tag).get('publications', {}).get(project, {})
    identical = bool(receipt) and previous and all(previous.get(k) == v for k, v in receipt.items())
    if identical and previous['unsigned_files'] != unsigned:
        raise RuntimeError('Different package content under the same publication identity')
    if not identical:
        authority = Path(os.environ.get('PACKAGE_SITE', ROOT / 'site')).parent / 'keys'
        key = 'opkg.pub' if row['family'] == 'openwrt' and row['suite'] == '24.10' else (
            'apk.pem' if row['family'] == 'openwrt' else 'apt.asc')
        if (ROOT / 'keys' / key).read_bytes() != (authority / key).read_bytes():
            raise RuntimeError('Capture verification key differs from deployed authority; a fresh capture is required')
        node = generation.get('nodes', {}).get(row['id'] + '/' + project, {})
        if receipt and (node.get('source') and node['source'] != receipt['source'] or previous.get('source', {}).get('run') == receipt['source']['run'] and previous['source']['attempt'] > receipt['source']['attempt']):
            raise RuntimeError('Superseded build attempt')
        activate(bundle, row['id'], json.loads(os.environ.get('BUILD_BASELINE', '{}')) or None, project)
        if digest(bundle / 'profiles.json') != generation['profiles_hash']:
            raise RuntimeError('Target source selection changed')
        if project not in generation['revisions']:
            raise RuntimeError('Project is not selected for this release')
        # Verify dependencies against the actual build manifest, and preserve unrelated
        # products from the current feed inside this serialized publication transaction.
        binding = json.loads(os.environ.get('BUILD_BASELINE', '{}'))
        state = read(root / 'status.json', {'runs': {}}) if state is None else state
        if (node.get('cause', generation['context'].get('cause')) == 'dependent'
                and cascade_blockers(current, dependencies(project), state, row['id'], work_index(state))):
            raise RuntimeError('Superseded build: prerequisite arm not current')
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
        # Retain independent product versions, each with its pinned ownership facts.
        releases = copy.deepcopy(current.get('releases', {}))
        retained = [entry for p, values in releases.items() for t, entry in values.items() if (p, t) != (project, tag)]
        files = dict(unsigned)
        for entry in retained:
            owners = ownership(entry)
            if any(not any(project_file(n, p, owners) for p in owners) for n in entry['files']):
                raise ValueError('Release inventory contains unowned files')
            for name, checksum in entry['files'].items():
                if name in files and files[name] != checksum:
                    raise ValueError('Conflicting retained release bytes: ' + name)
                files[name] = checksum
                relative = (Path(row['distribution']) / 'pool' / row['suite'] / name
                            if name.endswith('.deb') else Path(feed_paths(row)[0]) / name)
                if digest(root / relative) != checksum:
                    raise RuntimeError('Published sibling checksum mismatch')
                (directory / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / relative, directory / name)
        controls, identities = {}, set()
        own = dict(sources={project: metadata['sources'][project]}, files=unsigned,
                   versions={project: package_version(row, profile['context']['versions'][project], generation['revisions'][project])})
        for entry in [*retained, own]:
            owners = current_owners | incoming_owners | ownership(entry)
            for name in entry['files']:
                if name.endswith(('.deb', '.rpm', '.ipk', '.apk')):
                    fields = package_metadata(directory / name)
                    validate_package(owners, entry['versions'], name, fields, row)
                    identity = tuple(fields[k] for k in ['name', 'version', 'arch'])
                    if identity in identities:
                        raise ValueError('Duplicate package identity: ' + name)
                    identities.add(identity)
                    controls[name] = fields
        for name in metadata['files'].keys() - files.keys():
            (directory / name).unlink()
        metadata['files'] = files
        own_names = sorted({controls[n]['name'] for n in unsigned if n in controls})
        metadata['packages'] = sorted({fields['name'] for fields in controls.values()})
        own_versions = own['versions']
        releases.setdefault(project, {})[tag] = dict(revision=metadata['revision'], sources={project: metadata['sources'][project]},
            context=profile['context'], files=unsigned, unsigned_files=unsigned, versions=own_versions, packages=own_names)
        metadata['releases'] = releases
        highest = {p: values[max(values, key=version)] for p, values in releases.items()}
        metadata['versions'] = {k: v for entry in highest.values() for k, v in entry['versions'].items()}
        metadata.update(context=profile['context'], sources=profile['sources'])
        write(manifests[0], metadata)
        if row['family'] == 'openwrt':
            from ci.publish.openwrt import reindex
            reindex(directory, metadata, controls)
            write(manifests[0], metadata)
        if row['family'] == 'openwrt':
            importlib.import_module('ci.repository').publish(incoming, root, bundle)
        elif row['family'] == 'raspberrypi':
            importlib.import_module('ci.publish.apt').publish(incoming, root, bundle)
        else:
            importlib.import_module('ci.publish.linux').publish(incoming, root, bundle)
        info, directory = published(root, row)
        shutil.copytree(authority, root / 'keys', dirs_exist_ok=True)
        importlib.import_module('ci.publish.cleanup').cleanup(root, row)
        info, directory = published(root, row)
        info['published_at'] = datetime.now(timezone.utc).isoformat()
        entry = releases[project][tag]
        entry['files'] = {n: info['files'][n] for n in unsigned}
        entry['publications'] = {project: receipt | dict(revision=generation['revisions'][project],
            published_at=info['published_at'], unsigned_files=unsigned)}
        info['releases'] = releases
        for key in ('sources', 'versions', 'publications'):
            info[key] = {k: v for entry in highest.values() for k, v in entry[key].items()}
        for key in ('source_tags', 'versions'):
            info['context'][key] = {p: entry['context'][key][p] for p, entry in highest.items()}
        manifest = root / directory / 'build.json'
        aggregate = read(manifest)
        if 'targets' in aggregate:
            aggregate['targets'][row['arch']] = info
        else:
            aggregate = info
        write(manifest, aggregate)
    return None


def readme_blocks(text, previous=''):
    """Carry generated blocks across authored updates; only render produces their content."""
    pattern = r'(<!-- packages:begin (projects|platforms) -->).*?(<!-- packages:end \2 -->)'
    blocks = {match[2]: match[0] for match in re.finditer(pattern, previous, flags=re.S)}
    return re.sub(pattern, lambda match: blocks.get(match[2], match[1] + '\n' + match[3]), text, flags=re.S)


def merge_readme(root, previous, remote):
    """Merge authored text while retaining the remote's generated blocks."""
    def blob(ref):
        return subprocess.check_output(['git', '-C', str(root), 'show', f'{ref}:README.md'], text=True) if run('git', '-C', str(root), 'ls-tree', ref, '--', 'README.md') else ''
    readme = root / 'README.md'
    base, theirs = blob(previous), blob(remote)
    ours = readme.read_text() if readme.exists() else ''
    if base and not theirs:
        raise RuntimeError('Remote README removed; refusing to replace authored content')
    if any((base, theirs, ours)):
        with tempfile.TemporaryDirectory() as temporary:
            paths = [Path(temporary) / name for name in ('ours', 'base', 'theirs')]
            for path, text in zip(paths, (ours, base, theirs)):
                path.write_text(readme_blocks(text))
            result = subprocess.run(['git', 'merge-file', '-p', *(str(path) for path in paths)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError('Conflicting authored README edits; refusing to replace them')
            readme.write_text(readme_blocks(result.stdout, theirs))
    return None


def copy_site(root):
    site = Path(os.environ.get('PACKAGE_SITE', ROOT / 'site'))
    readme = root / 'README.md'
    readme.write_text(readme_blocks((site / 'README.md').read_text(), readme.read_text() if readme.exists() else ''))
    if (root / 'docs').exists():
        shutil.rmtree(root / 'docs')
    shutil.copytree(site / 'docs', root / 'docs')
    if (root / 'install').exists():
        shutil.rmtree(root / 'install')
    shutil.copytree(site.parent / 'install', root / 'install')
    (root / 'keys').mkdir(exist_ok=True)
    shutil.copy2(site / 'keys/README.md', root / 'keys/README.md')
    return None


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
            if (os.environ.get('GITHUB_WORKFLOW_REF') !=
                    f'{COORDINATOR}/.github/workflows/control-packages.yml@refs/heads/{os.environ.get("PACKAGE_COORDINATOR_REF", "main")}'
                    or os.environ.get('GITHUB_REPOSITORY') != COORDINATOR):
                raise ValueError('Only the serialized coordinator may change admission state')
            from ci.dispatch import change
            change(root, read(Path(args[1])))
        else:
            if (os.environ.get('GITHUB_REPOSITORY') != COORDINATOR or os.environ.get('GITHUB_WORKFLOW_REF') !=
                    f'{COORDINATOR}/.github/workflows/orchestrate-packages.yml@refs/heads/{os.environ.get("PACKAGE_COORDINATOR_REF", "main")}'):
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
        state = read(root / 'status.json', dict(repository=FEED, branch=FEED_BRANCH, counters={}, runs={}))
        context = read(bundle / 'context.json')
        if state.get('repository') != context['destination'] or state['branch'] != FEED_BRANCH:
            raise RuntimeError('Publication destination mismatch')
        generation = record_run(bundle, state, context)
        attempt = int(os.environ.get('BUILD_ATTEMPT') or os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
        if command == 'status':
            target, project, status = args[2:5]
            if target == '-' and project == '-' and status == 'pending':
                for row in generation['targets']:
                    for project in (p for p in generation['revisions'] if supports(p, row, read(bundle / 'profiles.json')[row['id']]['projects'])):
                        profile = read(bundle / 'profiles.json')[row['id']]
                        missing = missing_prerequisites(project, profile.get('baseline', {}), generation['revisions'], profile['projects'])
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
                publish(root, bundle, Path(args[4]).resolve(), row, generation, project, state)
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
