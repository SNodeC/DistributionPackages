# Deployment-owned package status templates

This bundle is part of the trusted worker tooling commit. Customize it in the worker
repository, review it, and upgrade the matching approved tooling/workflow pins together.
Source repositories and build artifacts cannot provide templates or presentation settings.

The renderer replaces the hard-coded status-page assembly. It does not schedule work or
change whether a package is eligible/published. Rendering runs in a bounded subprocess with
no inherited GitHub/signing credentials, after temporary signing files have been removed and
before the sole feed push step. A template error fails preparation; it does not imply that
an already-started push failed. No template/rendering dependency is added to the controller.

## Files and configuration

- `presentation.json`: schema 1, `title`, public `parameters`, optional `projects` and `assets`.
- `index.html.j2`: HTTPS root and status index HTML.
- `index.md.j2`: GitHub status index Markdown.
- `project.md.j2`: project-specific GitHub Markdown and HTTPS HTML, with safe HTML tables.
- `table.html.j2`: shared include; templates can use includes/macros in this bundle.
- `requirements.txt`: pinned GitHub-side Jinja2/MarkupSafe dependencies.

Owner-defined `parameters` need no new controller option for each field. For example:

```json
{
  "schema": 1,
  "title": "My package feed",
  "parameters": {"support_url": "https://example.org/support", "introduction": "My public introduction"},
  "projects": {"Example/library": {"title": "Example Library", "page": "library", "catalog_url": "https://example.org/catalog"}},
  "assets": ["assets/logo.svg"]
}
```

A template can use `{{ site.parameters.introduction }}` and
`{{ project.parameters.catalog_url }}`. Only explicitly public settings belong here.
Project `page` selects a bounded status-page basename, so `snode.c` can use `snodec.md`
without a compiled-in repository mapping. The template context exposes `project.status_path`;
colliding output names fail explicitly. Required missing variables raise errors; absent optional facts use null/empty values.
HTML escaping is enabled for every output. Default Markdown uses HTML tables so package
metadata cannot introduce Markdown table/link syntax. Custom Markdown outside HTML needs
appropriate Markdown-context escaping; HTML escaping alone is not sufficient there.

Assets must be regular files below this bundle's `assets/` directory and are copied only
below feed `status/assets/`. Links, traversal and linked output parents are rejected.
The bundle is bounded to 4 MiB, each rendered page to 4 MiB and total outputs to 32 MiB.
Rendering does not accept arbitrary output paths. Keys, package bytes, receipts and signed
indexes are not output destinations. Templates remain trusted deployment code; this is not
an invitation to execute arbitrary hostile templates in a privileged workflow.

## Template context

`publications` retains the existing repository/target/package/version, source commit,
checksum and package/receipt/build/publication URL fields. It adds structured `coordinates`,
selected `target_row`, selected `source`, `revision`, `dependencies`, `environment`, `summary`, `build_job`,
`build_duration_seconds` and `published_utc`.

`projects` groups these rows by repository. A project contains `repository`, display `title`,
owner `parameters`, all its `publications`, and coordinate-grouped `targets`. Each target
contains `coordinates`, retained `publications` and recorded `executions` in descending rebuild
revision order. `project.versions` contains accepted selected source tags in the controller's
existing numeric SemVer order (including prereleases). The template chooses which version
and work to display; it does not decide which source to build or implement a version comparator.
The default template selects the first source version and shows only a matching publication
for each target. When that version has not published, Available is `—`, even if older packages
are retained. Set `site.parameters.show_history` to true to include retained publication tables.
`project.parameters.navigation` maps public navigation labels to trusted deployment URLs.
The context is also written to `status.json`; the existing `publications` array stays present.
Rows include only package files still present in the retained feed tree. The field
`development_export_available` distinguishes retained installation packages from build inputs
whose development export has expired. Public controller executions cover retained/live work
and referenced prerequisites; the highest selected source version remains available to the
presentation even if it has no retained publication. Cleanup progress is shown in the local
controller view rather than emitted as package publication status.

New receipts retain compact selected-prerequisite references: execution/attempt and assignment
identities, source, revision, compatibility, packages, development export and feed. They do not
recursively embed prerequisite receipts or capture another graph snapshot. These describe
consumed immutable inputs; they cannot show the prerequisite's current controller state.

Job timing is read from the already verified assigned GitHub job, without another API call.
The unprivileged trusted validator attaches it only after rejecting source artifacts that
claim verified job facts. Publication rechecks its run/job/attempt binding against the
assignment's build result. Duration is completed-at minus started-at for that whole build job;
it includes setup/upload/cleanup, not only the compiler's runtime. Missing times remain null.

Compiler/test data is optional **hook-reported display information**, not independently
attested testing and never permission to publish. The hook may add this to `outputs.json`:

```json
{
  "packages": [{"file": "library.deb", "component": "library"}],
  "summary": {
    "compilers": [{"name": "cc", "version": "actual compiler version"}],
    "tests": {"passed": 42, "failed": 0, "skipped": 1, "coverage_percent": 78,
              "report_url": "https://example.org/public-test-results"}
  }
}
```

Compiler strings and arrays, test counts, optional coverage and HTTPS report links are
bounded/validated and carried through manifest verification into the new publication receipt.
Summary keys cannot replace source, target, assignment, run or publication state. The native
reference hook reports the compiler it invoked and its one actual successful runtime test.
Old receipts remain untouched; facts not recorded in them stay null.

## Public graph facts and refreshes

Configure `pipeline.status-workflow` and `pipeline.status-workflow-blob` on the controller.
The existing public TLS listener then serves `GET /public/status`; the local listener exposes
the same read-only projection for inspection. No administration route is added to TLS.
The projection explicitly lists selected versions, target coordinates, current execution
states/activity, prerequisite IDs/blockers, failure reasons and already verified job links.
Each target's `executions` expose whitelisted `build_job` and `publication_job` facts from
GraphStore's existing evidence view: run/job status and IDs, recorded start/completion times
and conclusions. Verified running jobs can supply Build log before artifact publication;
there is no second timing/status collector. The SSE heartbeat remains transport-only.
It excludes assignments, build hooks, deployment configuration and credentials.
Only accepted graph selections appear; an unreadable definition is not silently invented.

After a successful graph commit, startup, or explicit local reconciliation request, the
controller dispatches `core-ci-status.yml` with the committed generation only. Configure
worker variable `CORE_CI_STATUS_URL`, for example
`https://gw-home.vchrist.at:8443/public/status`. The workflow fetches current facts after
acquiring the feed write lock. Delayed notifications therefore render current facts.
`status/controller.json` and `status.json` are public projections, never execution authority.
Older generations and conflicting content at the same generation are rejected.

The status-only workflow uses the existing feed-writer secret, not signing secrets. It and
publication share a feed concurrency group with `queue: max`; a separate status concurrency
group coalesces pending refreshes without cancelling a package publication. GitHub's bounded
pending capacity still applies. All writers use normal checked pushes; conflicts and uncertain
push results are not automatically retried. An explicit controller reconciliation requests a
fresh status render. A crash before notification needs such a refresh or the next graph change.
Pages updates are asynchronous; this is a public snapshot, not the management UI's live SSE.

`published_utc` is bound by execution/attempt to the controller's recorded
`publication_verified_utc`: the first successful verification of the public publication,
not a claimed exact push instant. Historical unrecorded times remain null.
The template renders UTC minutes. Verified current job evidence and successful build receipts
supply source-job links; before a job is verified, Build log remains absent. Templates may
present recorded conclusions such as cancelled, while the five graph states remain unchanged.
Unrecorded conclusions are not invented from failure text.
Source-reported compiler/test summaries remain labelled as such. Deployment templates may
supply navigation, artwork and alternative layouts using the same facts.

Run locally with the pinned dependencies installed:

```sh
python3 deployment/worker/core_ci/feed_status.py --feed /absolute/feed --templates /absolute/trusted-bundle
```

The CLI prints the exact generated path list. It does not push, sign packages, execute hooks,
contact GitHub or change graph state. Local fixture tests are not live GitHub acceptance.

The job timestamp fields come from [GitHub’s assigned job API](https://docs.github.com/en/rest/actions/workflow-jobs#get-a-job-for-a-workflow-run).
Template syntax and escaping follow the [Jinja documentation](https://jinja.palletsprojects.com/en/stable/templates/).
