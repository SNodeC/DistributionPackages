# Distribution packaging refactor: discussion and plan

> Historical record from SNodeC/OpenWRT. Paths and workflow descriptions below
> describe the predecessor, not the active configuration of this repository.
> See [current maintenance documentation](../maintainers.md).

Recorded on 28 September 2026. This document tracks the agreed design and
implementation status. Installation instructions live in the distribution guides.

## Release-tag implementation — 29 September 2026

Release builds use independent `vMAJOR.MINOR.PATCH` tags. Creating or moving a
matching tag in either upstream repository requests a build through the
`release-tag-changed` event, replacing the former OpenWRT, RaspberryPiOS and Linux
notifications. Deleting a tag does not request a build. Prerelease suffixes are not accepted by this production workflow.

Before tagging, commit the intended version to the upstream `VERSION` file.
CMake uses the reachable release tag with the fewest intervening commits,
breaking ties by highest semantic version. Uncommitted changes are allowed.
Release CI verifies that the selected tag matches the committed VERSION file.
Archives and clones without a reachable release tag use VERSION; no generated file needs to be inserted into GitHub's automatic archives.
Development checkouts keep the selected tag's numeric version and SONAME,
without an inferred Git-distance suffix. ABI-breaking development must account
for that retained ABI version. Reconfigure after changing tags. Existing submodule
requirements still apply when building a source archive.

Library VERSION follows each project's release. Its own libraries retain the
existing major-number SOVERSION policy: incompatible ABI changes require a major
version increment. MQTTSuite's SNode.C WebSocket plugins retain SNode.C's ABI major,
not MQTTSuite's major.

| Trigger | Source selection | Build and publication |
| --- | --- | --- |
| Created or moved SNode.C tag | New SNode.C, then the highest stable `vMAJOR.MINOR.PATCH` MQTTSuite tag | Publish SNode.C first; only then build and publish the corresponding MQTTSuite target |
| Created or moved MQTTSuite tag | New MQTTSuite plus each target's published SNode.C | Build and publish MQTTSuite only |

Each distribution/version/architecture has its own independent chain:

1. Build and test SNode.C.
2. Push its packages and signed indexes to `packages` immediately.
3. After that push succeeds, build MQTTSuite against those published SNode.C packages.
4. Push MQTTSuite's packages and signed indexes immediately.

No target waits for another architecture. If the MQTTSuite build fails, the already
published SNode.C remains available. If SNode.C publication fails, that target's
MQTTSuite build does not start. Package-branch writes are serialized to prevent
conflicting pushes; builds have no whole-matrix publication barrier. New runs
start building after source preparation without entering the publication queue.
Cancellation stops pending publication and log-upload work as well as builds.

All 76 target workflows expand after preparation. Their build jobs use 19 native
GitHub concurrency groups per run, so waiting builds remain queued as actual
jobs instead of being hidden behind an outer matrix admission limit. A target's
SNode.C and MQTTSuite builds share its assigned group. Publication uses its own
writer group. The 19-build limit leaves headroom under the 20 observed runner
slots for one run; it is not a reservation across overlapping runs. Publication
checks out only the affected feed and shared
metadata using Git's partial and sparse checkout. APT includes the whole suite
because its signed release metadata covers all architectures. Retention validates
and cleans that feed only, preserving other feeds' files and retirement records.
The atomic snapshot push remains serialized and protected by a Git lease.

Each target has separate SNode.C and MQTTSuite status badges linked to their
respective jobs. Separate project READMEs use flat tables with distribution, release,
architecture, version, status, publication date and package links. Each project
has its own installation guide; distribution guides own shared repository setup. Status snapshots distinguish waiting,
building, publishing and published packages, and refresh during publication.

Package revisions derive from the entry workflow's increasing run number `N`:
SNode.C uses `2*N`, and MQTTSuite uses `2*N+1`. Retries keep the same revisions;
new runs receive distinct revisions without a shared allocation job. Run history
is recorded on the first target result, rather than before compilation. Existing
counterpart packages retain their exact bytes, version and source provenance until
that project's own build succeeds. The publisher rejects stale dependencies and
verifies each artifact against the captured source selection. Recorded commit IDs
verify version tags; they are not source selectors.

Linux and Raspberry Pi OS install the published SNode.C development packages.
OpenWrt also publishes `snode.c-sdk-<version>-r<revision>.tar.zst`, containing the
SDK's installed headers, libraries and library dependency metadata. It contains no
source tree, build tree or build stamps. MQTTSuite restores these files into the
same SDK release and architecture, relocates installed CMake/pkg-config metadata,
and skips SNode.C compilation and tests. Missing development files require a
SNode.C release first; an application-only release never rebuilds the library.

The upstream repositories have only README TOC updates and version-tag
notifications. This repository accepts only those release notifications and uses
internal reusable workflows. There are no manual build entry points, scheduled
cleanup workflows or separate completion-triggered status workflows. Retention
cleanup and publication-status updates run within the publication writer.

Version-tag creation, movement and pushes require explicit user approval. CI must
not be started by the assistant without an explicit instruction. The 76-target
matrix is retained.

## Production cutover — 29 September 2026

The full 76-target validation run [36406257089](https://github.com/SNodeC/OpenWRT/actions/runs/36406257089)
and its completion handler passed. All 76 development feeds published successfully.

The validated orchestration now lives on `main`. The existing
`openwrt.yml` entry point now invokes the full reusable matrix for both manual
runs and the existing source-tag notifications. All targets publish individually
to `packages`, through one serialized writer. Daily/manual retention and run
completion use the same writer. The development dispatcher and separate
maintenance schedule are removed. User documentation points exclusively to the
production feed and its generated publication README.

Existing source-tag names and upstream notification workflows are unchanged;
each accepted notification selects that tag in both upstream projects for the
full matrix. A new common release-tag policy, repository renaming and upstream
version derivation remain separate work. Historical development branches are
not inputs to production workflows.

The user explicitly approved promoting the validated revision-3 packages over
the older production revisions 50–52 without a rebuild. All 76 targets resolve
to exactly the same upstream source commits in both snapshots. Package bytes,
checksums, signatures and recorded build provenance remain unchanged. The
production snapshot preserves old payloads and retirement dates for cached
clients; the active indexes come from the validated development snapshot.
Future allocations continue from the promoted publication history.

The sections below record the development history and original decisions.

## Starting point and scope

Work takes place on `refactor/distribution-packages`, starting from main commit
`f1a21e6a909a699ddb688d6719f78fd067a56938`. The temporary
`backup/main-before-recipe-sync-20260927` branch was explicitly deleted locally
and on GitHub. The current production workflow remains operational on `main`.

The repository now serves OpenWrt, Raspberry Pi OS, Debian, Ubuntu, Rocky Linux
and Fedora. Treat them consistently in build status, publication, repository
access and installation documentation. Their native packaging mechanisms still
differ; consistency does not mean forcing them into the same build environment.

The current matrix contains 50 OpenWrt combinations, two Raspberry Pi OS
combinations and 24 other Linux combinations. Preserve the supported release
and architecture definitions throughout the refactor.

## Recipe ownership and branches

Keep the canonical OpenWrt recipes together on `main`:

- `net/snode.c/`
- `net/mqttsuite/`

CI should consume the recipes and orchestration from one captured packaging
repository commit, rather than independently moving recipe branches.

The earlier proposal to synchronize permanent `SNode.C` and `MQTTSuite` recipe
branches and merge them back into main was superseded. The preferred direction
is to retire those branches after verifying that no unique work needs preserving.
They have not yet been deleted. This concerns branches of the packaging
repository, not the separate upstream source repositories.

Current main already contains the working recipes. The old recipe branches still
contain obsolete source patches and test/configuration files; these must not be
reintroduced. Do not add source patches, rewrite upstream sources in CI, or move
CPack policy into CI. DEB/RPM component packaging remains upstream; OpenWrt
package selection and configuration remain in its recipes.

The obsolete `ci/openwrt-32bit`, `ci/openwrt-infra` and `ci/openwrt-packages`
branches and their associated local worktrees were already removed.

## Build and test organization

Use independent matrix instances for each distribution, release and architecture.
Each instance has its own build/test result, logs, artifacts and publication.
Do not create one duplicated workflow file per combination. Reusable workflows
may separate genuinely different build mechanisms:

- OpenWrt: official SDK and target execution through QEMU where applicable.
- Raspberry Pi OS: official OS-image filesystem.
- Other Linux distributions: appropriate distribution containers, with native
  execution or QEMU as required.

Run available upstream tests. Keep test policy in upstream test configuration;
do not recreate duplicate application test suites in the packaging repository
or introduce production test hooks.

At the start of development, run only these three representative combinations:

| Family | Release | Architecture |
| --- | --- | --- |
| Linux | Debian Trixie | amd64 |
| OpenWrt | 25.12 | x86_64 |
| Raspberry Pi OS | Trixie | arm64 |

Keep the complete matrix defined, but select this subset for development runs.
Use an isolated publication destination so development output cannot replace
production feeds. The development destination is `packages-dev`; production `packages` is unchanged. Once the
mechanics work, enable the full matrix for architecture and release validation.
The subset alone cannot validate every package format, older distribution or ABI.

## Independent publication

The preferred design supersedes the earlier all-matrix publication gate:
publish a combination as soon as its own build and tests succeed. Other running
or failed combinations must not block it. A failed combination keeps its last
successfully published packages.

Serialize writes to the shared `packages` branch. Every publisher must start from
the latest snapshot, update only its destination and preserve other publications.
Reject stale builds that would replace newer packages. Never lose another
publisher's changes when updating the single-commit snapshot.

Repository boundaries determine the update operation:

- OpenWrt feeds have independent release/architecture directories.
- RPM feeds have independent distribution/release/architecture directories.
- APT suites share release metadata across architectures. Publishing one
  architecture must preserve the other architectures, then regenerate and sign
  the suite metadata coherently.

Preserve native repository layouts, package and index signing, source provenance,
and the existing retention policy. Superseded, unreferenced files remain for
30 days; cleanup runs during publication and scheduled maintenance. Current
referenced packages remain protected. Keep one authority for APT index generation.

Capture both upstream source revisions once per run. Use tags as the user-facing
source selectors and record resolved commits for reproducibility, rather than
replacing tag selection with hard-coded commit pins. Define publication ordering
and stale-run behavior explicitly before enabling concurrent live publication.

## README status and user documentation

Show status per distribution/release/architecture using badges and a table.
Separate two facts:

- Latest build: running, passed or failed, with a link to its run.
- Published feed: SNode.C and MQTTSuite package versions, publication date,
  source provenance and package/feed links.

A failed latest rebuild does not make an existing feed unavailable. Derive
published information from feed manifests, not merely workflow success. GitHub's
ordinary workflow badge does not directly represent individual matrix results;
per-combination badges are generated from recorded build results.

Keep generated publication information on the `packages` branch and link to it
from the main README. Avoid committing generated status to main after every
build. During development, show the three development combinations separately
from production publication status; expand coverage with the full matrix.

Remove CI-development history, obsolete validation explanations and feed-directory
migration sections from user-facing documentation. Preserve installation scripts,
manual installation, release/architecture tables, catalogs, feed links, updates
and useful troubleshooting, consistently for all distributions.

Give remaining non-main branches a concise README describing their actual
purpose where needed. Do not replace main's user-facing README with a branch
description. The published README is copied from `docs/package-repository.md`
during both publication and cleanup, so edit that authority rather than making
an isolated change that the next run overwrites.

Branch-specific README merge scripts and required PR checks were discussed but
not adopted. Retiring permanent recipe branches removes the main reason for that
extra machinery. No new branch protections or merge automation were authorized.

## Repository name

The proposed name is `SNodeC/packages`; `linux-packages` was another option.
No rename has happened, and the final rename remains a separate step.

Renaming the existing repository is preferred to creating a new repository: retain
history, settings, GitHub App integration and existing feeds. Update and verify
workflow references, installer URLs, documentation and package-manager feed URLs
together. Do not rely on GitHub redirects without testing package-manager access.

## Release triggers and tag-driven versioning

The initial proposal was one movable tag in each upstream repository, replacing
the separate `OpenWrt`, `RaspberryPiOS` and `Linux` trigger groups. Names discussed
included `Packages` and `Packaging`; no final new tag name was selected.

The discussion then moved toward real upstream release management:

- Use conventional versioned tags such as `v2.0.1` for SNode.C and `v1.0.2` for
  MQTTSuite. The projects have independent version sequences.
- Consider triggering packaging when a GitHub Release is published, with an
  explicit policy for prereleases, rather than treating every matching tag push
  as a production release.
- Select and record an explicit compatible pair of upstream releases. A release
  in one project must not silently select an arbitrary revision of the other.
- Published versioned release tags stay fixed. Packaging-only rebuilds increment
  the package revision, which package managers also compare when upgrading.

Tag-derived upstream CMake versions are possible, but are a separate task:

| Source form | Required version policy |
| --- | --- |
| Exact release tag | Derive MAJOR.MINOR.PATCH from that tag |
| Development checkout | Identify development commits distinctly from a release |
| Prepared release archive | Carry version metadata derived from the tag |
| Clone without usable tags or metadata | Explicit override or clear failure |
| Automatic GitHub source archive | Provide a deliberate export/fallback mechanism |

Calling `git describe` alone is insufficient for all these cases. A normal clone
usually fetches tags, but shallow or no-tags clones may not. Automatic GitHub
source archives do not automatically acquire files generated by a release job.
Archive metadata export and prepared release assets were discussed as options;
the final implementation is not selected.

Library VERSION can follow the release version. Deriving SOVERSION from the
release major is valid only with an explicit rule that ABI breaks require a major
release. Development builds after an ABI break need the upcoming ABI generation,
not blindly the previous release's major. Libraries/plugins governed by another
project's ABI require separate consideration. Do not change SOVERSION mechanically
before that policy is settled.

## Agreed implementation sequence

1. Refactor CI and publication first, keeping current upstream versioning and tag
   selectors initially. Use manual/refactor-branch runs and the three-job subset;
   keep production triggers operational until deliberate cutover.
2. Validate partial publication, preservation of other architectures, stale builds,
   concurrent writers, signatures and retention against temporary snapshots.
3. Enable and validate the entire matrix before calling the CI refactor complete.
4. Clean user documentation and carry out the repository rename as a coordinated,
   separately verified change.
5. Implement upstream tag-driven release/version handling separately, after
   choosing archive, development, prerelease and ABI policies; then connect it to
   package CI and retire the old trigger scheme.

No production C++ changes are planned for the CI refactor. Upstream release
notification and versioning changes require their own review. This document
records the direction and outstanding decisions; it does not claim that the
refactor, branch retirement, rename or release-versioning work is complete.

## Development implementation

The reusable `packages.yml` workflow now selects all 76 targets for validation.
`packages-development.yml` is the manual entry point on `main`; it accepts
independent existing upstream tags and invokes this branch.
`packages-maintenance.yml` handles cancelled/failed run status and retention.
Existing production workflows and triggers remain unchanged.

Each target runs its native build and upstream tests, then independently publishes
through `package-write.yml`. This writer serializes revision allocation, status,
publication and cleanup on `packages-dev`, uses force-with-lease and retains a
single parentless snapshot. Revisions increase across runs; retries retain their
revision, and conflicting or stale publications are rejected.

APT publication preserves other architectures using the current per-architecture
manifest and regenerates signed suite metadata in one place. Retained payloads
are not automatically reintroduced into indexes. The full 76-target definition
is enabled by the development dispatcher, still publishing only to `packages-dev`.

Development status and feed versions are generated in
[archived validation snapshot](../maintainers.md#branches-and-history).
A failed build retains the last successful feed and its published version.

Local publication checks cover partial APT updates, legacy manifest import,
identical retries, stale revisions, signed metadata, retention, snapshot writer
conflicts and monotonic status updates. Real APT clients also validate signed
indexes with forced by-hash downloads.

The [first development run](https://github.com/SNodeC/OpenWRT/actions/runs/36385083597)
passed all 212 upstream tests on each target and published them independently:
Raspberry Pi OS at 06:26 UTC, Debian at 06:32 and OpenWrt at 06:43 on 28 September.
The completion handler passed, and the published branch retained one parentless
commit. Production workflows and feeds were unchanged.

A subsequent native APT client check found that Release metadata advertised
SHA512 while only SHA256 by-hash paths were published. The index generator now
advertises SHA256 consistently. Temporary signed feeds pass forced by-hash
client checks. The [second development run](https://github.com/SNodeC/OpenWRT/actions/runs/36391172432)
also passed all 212 upstream tests on each target and independently published
revision 2. Native APT clients verified signatures and mandatory SHA256 by-hash
index downloads against both public development feeds without fallback. The
completion handler passed; the final snapshot has no parent commit. Retention
protected 241 current files and retained 230 superseded files for the grace period.

Failure rollback, stale writer rejection, partial APT updates, retry ordering,
legacy suite import and expiry of unreferenced files were verified with temporary
local fixtures. No application or test source was changed in either upstream
repository, and no extra application tests were added here.

The three-target development phase is validated. Full-matrix validation,
production cutover, retirement of obsolete branches, repository renaming and
upstream release/version policy remain separate outstanding stages. The
production workflow has not been replaced or retriggered by this development work.

| Development target | Latest build |
| --- | --- |
| Debian trixie amd64 | [Debian validation snapshot](../maintainers.md#branches-and-history) |
| OpenWrt 25.12 x86_64 | [OpenWrt validation snapshot](../maintainers.md#branches-and-history) |
| Raspberry Pi OS trixie arm64 | [Raspberry Pi OS validation snapshot](../maintainers.md#branches-and-history) |

## Publication README and landing-page integration

The generated publication README is the single target-status view. It lists the
complete canonical matrix, grouped by distribution and preserving its configured
architecture order, including targets that have not yet been built.
Targets without a recorded build display a neutral badge; targets without a feed
display `Not published` and no package links. These labels describe the validation
channel only, not production availability. Existing manifests remain the authority
for published versions, timestamps and provenance after failed rebuilds.

The project landing page and all six distribution guides link directly to the
corresponding sections of this README, which links back to installation guides and
production packages. The separate `STATUS.md` view is removed. The renderer is
reshaped without increasing its production line count; package content, build
selection, test execution and publication policy are unchanged.

## Full-matrix validation

Following the successful three-target runs and publication README review, the
development workflow selects the complete matrix: 50 OpenWrt targets,
two Raspberry Pi OS targets and 24 Linux targets. Source tags, build and test
steps, independent publication and serialized writes are unchanged. Production
feeds remain isolated. Monitor the complete run and report failures before
making fixes; enabling the matrix is not evidence that all targets have passed.

The first full-matrix run exposed a publication scheduling defect: per-target
`running` status writers queued before finished builds in the same FIFO group.
Remove those jobs so each target proceeds directly from build/tests to its own
publication job. Read running/queued job state from GitHub while refreshing a
publication, preserving recorded terminal results and attempt ordering. Status
lookup failures must not prevent package publication. Only actual publications,
revision allocation, final reconciliation and retention use the serialized writer.
Build and publication job names include the distribution, release and architecture.
The retired three-target selector is removed; the canonical matrix is unchanged.
