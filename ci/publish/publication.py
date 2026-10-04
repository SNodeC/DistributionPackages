"""One serialized writer for per-target publications and their displayed status."""
from datetime import datetime, timezone
from html import escape
import importlib
import json
import os
from pathlib import Path
import shutil
import sys

from ci.repository import ROOT, matrix, linux_matrix, run, select, project_file, digest, REPOSITORIES


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


def render(root, state):
    shutil.copy2(ROOT / 'README.md', root / 'README.md')
    shutil.copytree(ROOT / 'docs', root / 'docs', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'install', root / 'install', dirs_exist_ok=True)
    badges = root / 'status'
    badges.mkdir(exist_ok=True)
    sections = {}
    colors = {'pending': '#57606a', 'running': '#0969da', 'publishing': '#0969da', 'published': '#1a7f37',
              'failed': '#cf222e', 'cancelled': '#57606a', 'skipped': '#57606a', 'superseded': '#9a6700', 'not built': '#57606a'}
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
            width = len(status) * 7 + 16
            filename = f"{row['id']}-{project}.svg"
            (badges / filename).write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" aria-label="{escape(project)}: {escape(status)}"><rect width="{width}" height="20" rx="3" fill="{colors[status]}"/><text x="{width / 2}" y="14" text-anchor="middle" fill="white" font-family="Verdana,sans-serif" font-size="11">{escape(status)}</text></svg>\n')
            badge = f"![{project}: {status}](../status/{filename})"
            url = item.get('job_url', item.get('run_url'))
            badge = f'[{badge}]({url})' if url else badge
            version = f'`{version}`' if version else '—'
            sections.setdefault(row['distribution'], {}).setdefault(row['suite'], {}).setdefault(project, []).append(f"| `{row['arch']}` | {version} | {badge} | {date} | {links} |")
        (badges / f"{row['id']}.svg").unlink(missing_ok=True)
    text = (ROOT / 'ci/templates/package-status.md').read_text()
    for distribution, suites in sections.items():
        tables = []
        for suite, projects in suites.items():
            tables.append(f'### {suite}')
            for project, lines in projects.items():
                title = 'SNode.C' if project == 'snode.c' else 'MQTTSuite'
                tables.append(f'#### {title}\n\n| Architecture | Version | Status | Published | Packages |\n| --- | --- | --- | --- | --- |\n' + '\n'.join(lines))
        text = text.replace(f'<!-- targets:{distribution} -->', '\n\n'.join(tables))
    (root / 'docs/status.md').write_text(text)
    (root / 'STATUS.md').unlink(missing_ok=True)


def update(state, row, generation, project, status, attempt, job_url=None):
    key = f"{row['id']}/{project}"
    previous = state['targets'].get(key, {})
    revision = generation['revisions'][project]
    if (int(revision), attempt) < (int(previous.get('revision', 0)), previous.get('attempt', 0)):
        return
    state['targets'][key] = dict(target=row, revision=revision, attempt=attempt,
                                run_id=generation['run_id'], run_url=generation['run_url'], status=status,
                                job_url=job_url or (previous.get('job_url') if previous.get('run_id') == generation['run_id']
                                                   and previous.get('attempt') == attempt else None) or generation['run_url'])


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
    for row in rows:
        state['targets'].pop(row['id'], None)  # Replace the old combined result with project results.
        for project in revisions:
            previous = state['targets'].get(f"{row['id']}/{project}", {})
            attempt = int(os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
            if previous.get('run_id') != run_id or previous.get('attempt', 0) < attempt:
                update(state, row, generation, project, 'pending', attempt)
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
                or current.get('revision') not in generation['revisions'].values()
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


def reconcile(state, run_id, attempt):
    generation = state['runs'].get(run_id)
    if not generation:
        return
    endpoint = f'repos/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{run_id}'
    details = json.loads(run('gh', 'api', endpoint))
    if details['run_attempt'] != attempt:
        return
    lines = run('gh', 'api', '--paginate', f'{endpoint}/attempts/{attempt}/jobs?per_page=100', '--jq',
                '.jobs[] | {name, status, conclusion, html_url} | @json')
    jobs = {job['name'].rsplit(' / ', 1)[-1]: job for job in map(json.loads, lines.splitlines())}
    for row in generation['targets']:
        for project in (repo for repo in REPOSITORIES if repo in generation['revisions']):
            latest = state['targets'].get(f"{row['id']}/{project}", {})
            if latest.get('run_id') != run_id:
                continue
            publication = jobs.get(f'Publish {project} · {row["id"]}')
            job = publication or jobs.get(f'Build and test {project} · {row["id"]}', {})
            if latest['status'] not in {'pending', 'running', 'publishing'}:
                update(state, row, generation, project, latest['status'], attempt, job.get('html_url'))
                continue
            status = 'pending'
            if job.get('status') == 'in_progress':
                status = 'publishing' if publication else 'running'
            elif job.get('status') == 'completed':
                conclusion = job.get('conclusion')
                status = ('published' if publication else 'pending') if conclusion == 'success' else (
                    conclusion if conclusion in {'cancelled', 'skipped'} else 'failed')
            elif (project == 'mqttsuite' and generation['context']['release_project'] == 'snode.c'
                  and state['targets'].get(f"{row['id']}/snode.c", {}).get('status') in {'failed', 'skipped', 'superseded'}):
                status = 'skipped'
            if details['status'] == 'completed' and status in {'pending', 'running', 'publishing'}:
                status = 'cancelled' if details['conclusion'] == 'cancelled' else 'failed'
            update(state, row, generation, project, status, attempt, job.get('html_url'))


def main():
    command, *args = sys.argv[1:]
    if command == 'matrix':
        print(json.dumps({'include': targets()}))
        return
    if command == 'scope':
        row = json.loads(args[0])
        if row not in targets():
            raise ValueError('Unknown publication target')
        print('\n'.join(['**/build.json', '/README.md', '/docs/', '/install/', '/status.json', '/retention.json', '/status/', '/keys/']
                        + [f'/{path}/' for path in feed_paths(row)]))
        return
    root, bundle = (Path(p).resolve() for p in args[:2])
    state = read(root / 'status.json', dict(repository='SNodeC/Packages', branch='main', runs={}, targets={}))
    if state.get('repository') != 'SNodeC/Packages' or state['branch'] != 'main':
        raise RuntimeError('Publication destination mismatch')
    context = read(bundle / 'context.json')
    if context['destination'] != state['repository']:
        raise RuntimeError('Publication destination mismatch')
    result = 0
    if command == 'finish':
        generation = record_run(bundle, state, context)
        row = json.loads(args[2])
        project = args[5]
        if row not in generation['targets']:
            raise RuntimeError('Unknown publication target')
        status = args[3]
        if status not in {'success', 'failure', 'cancelled', 'skipped'}:
            raise ValueError('Unknown job status')
        if status == 'success':
            try:
                publish(root, bundle, Path(args[4]).resolve(), row, generation, project)
                status = 'published'
            except Exception as error:
                print(f'Publication rejected: {error}', file=sys.stderr)
                # Restore the checkout before recording failure; a partial local
                # assembly must never be pushed by the status update.
                run('git', '-C', str(root), 'reset', '--hard', 'HEAD')
                run('git', '-C', str(root), 'clean', '-fd')
                status = 'superseded' if 'superseded' in str(error).lower() else 'failed'
                result = 1
        else:
            status = 'cancelled' if status == 'cancelled' else 'failed'
        update(state, row, generation, project, status, int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')))
        try:
            reconcile(state, context['run_id'], int(os.environ.get('GITHUB_RUN_ATTEMPT', '1')))
        except Exception as error:
            print(f'Status refresh unavailable; keeping recorded results: {error}', file=sys.stderr)
    else:
        raise ValueError(f'Unknown publication operation: {command}')
    write(root / 'status.json', state)
    render(root, state)
    sys.exit(result)


if __name__ == '__main__':
    main()
