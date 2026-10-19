<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="media/nav/banner-documentation-compact.svg"><img src="media/nav/banner-documentation.svg" alt="DistributionPackages — Documentation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Documentation"><picture><source media="(prefers-color-scheme: dark)" srcset="media/nav/up-documentation-dark.svg"><img src="media/nav/up-documentation-light.svg" alt="Up to Documentation" title="Up to Documentation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/account-dark.svg"><img align="right" src="media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/organization-dark.svg"><img align="right" src="media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../README.md#banner" title="DistributionPackages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/repository-dark.svg"><img align="right" src="media/nav/repository-light.svg" alt="DistributionPackages repository" title="DistributionPackages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# CI orchestration

## Ownership and graph

[`ci/projects.json`](../ci/projects.json) defines repositories, package prefixes, dependencies and target families. Target definitions remain in `ci/targets/`. The immutable `source-pair` capture records exact commits, dependency revisions and sources, target coverage, the registry and tooling commit. Dependencies outside the selected release graph remain pinned at capture time.

DistributionPackages owns admission. GitHub runs and jobs are execution facts; signed feed `build.json` receipts and checksums are publication facts. Per-generation nodes in `status.json` are a recoverable projection, not the dependency scheduler's publication authority. Revision allocation remains in `reserve`. All metadata writes use the existing compare-and-swap transaction; signed feed writes remain serialized.

## Release and publication sequence

1. A `vMAJOR.MINOR.PATCH` push calls the standard notification workflow. A limited App dispatches capture with the project, exact tag commit and originating push run. Ordinary source branch pushes do not build packages.
2. Capture authenticates that push, allocates revisions, freezes source archives and tooling, and uploads `source-pair`. An untagged selected dependent is explicitly skipped; it does not prevent tagged prerequisites from building. Re-running capture reuses the saved artifact. A previously uploaded but expired capture cannot be silently reconstructed.
3. The controller wakes after capture or publication, on operator request, and at minute 17 hourly as recovery. It observes source runs across all registered repositories, checks actual feed receipts and admits ready per-target tasks. A selected dependent waits for all exact direct prerequisites, including at DAG joins.
4. Before dispatch, the controller persists a unique intent. Each source dispatch creates one target job. At most 16 source executions are admitted across generations; observed duplicates and manual runs consume capacity too. The remaining organization capacity is headroom, not a guarantee that unrelated workflows cannot use it. Emulated armhf and riscv64 builds each have one lane.
5. A source job uses only a read-only capture credential. Before project code runs, it must find its exact intent, run and attempt bound in the feed permit. The gate waits at most 60 seconds. Manual executions and late deliveries cannot bypass admission. Captured executable tooling and sources are verified before use.
6. Unsigned artifact upload completes the source handoff. The controller verifies the upload step, artifact identity and digest, including when later job cleanup fails. It dispatches one outstanding automatic publication request. Source code never receives a feed-writing credential or triggers publication directly.
7. Publication authenticates the source run, attempt, job and immutable artifact, verifies captured inputs and package checksums, signs using central secrets, preserves sibling products and writes the feed through the serialized snapshot transaction. Its receipt records capture, source execution, artifact digest, tooling and job URL. Replaying the same receipt and bytes is idempotent; conflicting bytes under that identity are rejected.
8. A later controller observation repairs status from the feed and immediately makes compatible dependents eligible. Failed or cancelled publication does not permanently skip them. A higher *pending* generation does not suppress older compatible work. If an actual newer feed revision replaces a captured dependency, the frozen task becomes explicitly superseded instead of changing its dependency contract.

The controller polls every 60 seconds while executions are outstanding. It hands off after 45 minutes; its job timeout is 50 minutes. Its concurrency group coalesces wakes rather than queueing one scheduler per event. GitHub API or runner delays can exceed the polling interval. Hourly recovery is not an availability guarantee: GitHub may delay schedules or disable inactive public-repository schedules. An operator can resume the controller without changing tags.

Dispatch requests have at-least-once delivery with fenced, idempotent effects. An unconfirmed intent expires after 120 seconds; its closure is persisted before another intent uses capacity. A bound execution retains capacity until GitHub confirms completion. Failed or incomplete API listings mean unknown, never absence. Automatic dispatch recovery stops after three attempts with an explicit failure requiring operator repair. No exactly-once delivery claim is made.

## Job links and status

The controller reads the exact run-attempt jobs endpoint and attaches the real source job `html_url`, including while queued. Before GitHub creates that job there is no link. Neither a coordinator URL nor a run overview substitutes for a job. A partial re-run is admitted as its own exact attempt; carried-over jobs are not assigned invented attempts. Published receipts retain their actual job link.

Presentation runs separately from control and signing. A renderer failure does not prevent a dispatch, signing or publication-failure report. Missing execution provenance can legitimately delay publication; optional page rendering cannot. Feed receipts outrank a failed or cancelled status for that same publication.

## Retry and recovery

Use **Coordinate package builds → Run workflow** to resume observation. To retry a repaired task, set `retry` to `capture/project/target`, for example `123456/snode.c/debian-trixie-amd64`. Retry is refused while that task has an admitted execution. Its existing verified artifact is retained for publication retries; without one it builds again. Re-running a failed source attempt still requires coordinator admission before project code executes.

Publication cancellation or failure leaves the unsigned artifact available for that explicit retry. If an artifact or immutable capture has expired, create a new deliberately authorized release capture; do not silently resolve tags again under the old generation. Duplicate or late dispatches cannot publish a different artifact under an existing receipt.

OpenWrt publication regenerates its unsigned index after rebasing retained sibling files from the current feed. Captured dependency checks remain mandatory; rebasing unrelated products never changes the build's dependency provenance.

## Adding a project

A new project needs four things: a registry entry, project recipe hooks under `ci/recipes/<project>/`, the standard thin source workflow, and operator-managed App access. No project-specific scheduler or renderer edit is needed. A native hook runs with the shared `package` helper; an OpenWrt hook runs with `compile` and declares relocatable SDK exports through `python3 -m ci.repository sdk-export`. Dependency exports are selected through registry edges. Recipe hooks own product build commands; generic infrastructure owns graph policy and feed integrity.

Copy an existing wrapper and configure the two limited credentials in [CI setup](setup.md#banner). Release tags must contain that wrapper, including maintenance-branch tags. An initial dependent tag may be added after registry registration: earlier captures explicitly skip that untagged dependent.

## Migration and validation

Freeze release notifications and drain all old captures, source jobs and publication jobs before merging. Provision the new limited credentials first. Merge DistributionPackages, then the three wrappers, while releases remain frozen. Verify wrappers and App permissions before resuming. There is no parallel old dispatcher: contract-1 captures are display history only and cannot be retried through contract 2. Old display history is imported into per-generation nodes. Remove the broad source App secret after all consumers have migrated; never remove signing keys from the coordinator.

`docs/maintainers.md` contains preserved historical operator notes and is not the contract for this migration.

```sh
python3 -m unittest discover -s tests -v
python3 tests/check_package_workflows.py /path/to/snode.c/.github/workflows/build-distribution-packages.yml /path/to/mqttsuite/.github/workflows/build-distribution-packages.yml /path/to/snode.c-idp/.github/workflows/build-distribution-packages.yml
```

Local fixtures exercise Git transactions, dispatch ambiguity, gate identities, queued links, failures, retries, overlap and feed signing. Live GitHub dispatch responses, limited-App artifact access, gate timing, cancellation, continuation and runner usage still require a separately approved sandbox with a test feed. Production dispatches are not a validation shortcut. No tag operation, installation or deployment is part of this change.
