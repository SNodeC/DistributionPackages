> Historical design/handover. Current publisher metadata checks, control-derived indexes, CAS graph validation and key authority are documented in [CI orchestration](ci-orchestration.md). Earlier capture-pinned feed-key copying is superseded.

> Historical design/evidence. Superseded by the canonical first-deployment agreement; current operations are in [setup](setup.md) and [orchestration](ci-orchestration.md).

# Repository-owned package CI: design and research

> The initial implementation below was independently reviewed and corrected. See [the correction handover](package-ci-corrections.md) for the current state, final tests and accounting; original evidence is preserved under `/tmp/codex/build/snodec/package-ci`.

This local refactor is based on DP main `9f30b2d2cf74c17870da5b1c279f3bf10443b88e`, not PR #30 or #31. Source bases are recorded in the handover. No deployment or live experiment is part of this design. The user authorized the four isolated task branches, per-target last-published selection, finish/discard overlap with latest explicit intent, and up to 650 net production/config/workflow lines across repositories.

## Invariants and architectural trace

A's flow was source notification → DP intake/reserve → immutable capture → source build → callbacks → central serialized signer/publication → direct dependent dispatch. Product commands and target lists were centrally owned; callbacks had no reconciliation and build concurrency groups were repository-local. C added a long-running controller, public-feed permits and fixed-cap admission, still kept product recipes centrally and conflated dispatch budgets. Neither is adopted wholesale.

The replacement retains the original capture/metadata/feed transaction boundaries and platform signers. Source JSON/hook ownership removes central target inventories, product command branches and specialized SDK handling. A single bounded controller replaces direct dependent dispatch and source finalizers. It uses callback claims plus GitHub execution facts, immutable captures and authoritative publication receipts. Public views are derived; they never grant execution permission. The existing CAS metadata writer is also the admission ledger; no additional database or service is introduced.

Before publication changes, the invariants to preserve were: one atomic CAS-safe feed writer; signing and verification before publication; admission and publication dependency checks; preservation of unrelated products in all formats; verified source/capture/tooling/artifact identities; monotonic revisions/attempts; identical-byte replay and conflicting-byte rejection; stable public URLs/keys/signatures; inventory-validated 30-day retention; skipped unpublished dependents; and DP-only signing secrets. Local tests exercise these boundaries; real OpenWrt signing remains an environment limitation recorded in the handover.

The root-first rolling feed is preserved. Per-row cascades use the exact last-published dependent commit/JSON, overridden by outstanding explicit intent. Diamonds wait for all in-cascade prerequisites. Pending explicit requests are selected again from the CAS-fresh state after reservation, so an interleaved framework capture cannot silently replace a newer application with an older published source. Exact commits are archived, independent of subsequent tag movement. Latest request means origin creation time with numeric source run ID as a deterministic tie breaker.

## Contract and state ledger

| Datum | Ownership and reason for persistence |
| --- | --- |
| Repo/tag/SHA/JSON digest, per-row source selection, profiles hash, revisions, capture/tooling identity | Immutable capture; tags move and artifacts expire, so historical intent cannot be reconstructed from current branches/tags |
| Latest explicit request per repository, origin time/run and reserved revision | Existing metadata ledger; moved/deleted tags lose the newer pending intent otherwise |
| Unique build/publication dispatch intent, pinned dependency publication commit | Existing node; required after a transport response is lost, before GitHub run binding is known |
| Source run/attempt/job, artifact ID/digest and separate source/publication dispatch counters | Existing node; reconcile execution via GitHub, retaining the admitted identity and independent bounded retry history |
| Dependency binding fingerprint and required names | Node; records the exact admitted prerequisite identities/revisions/files, including same-source package rebuilds |
| Held cascade source inputs digest (current approved correction) | Written only by CAS reserve; coarse tag/SHA/tooling/prerequisite release provenance for conditional cross-row revision sharing, never a checksum permit. Existing workflow serialization protects valid registration claims. |
| Last observer failure/category/backoff deadline | Existing ledger; GitHub cannot reconstruct this observer's failed observation or retry history; not a capacity authority |
| Publication receipt, source/revision/file manifests | Signed feed transaction; authoritative publication facts, including replay identity and retained sibling bytes |
| Target/timeline status pages | Derived from generations and feed facts; no separately persisted status reducer or permit authority |

Runtime `ci/definitions.json` is derived from capture-pinned definitions and ignored by Git. Captured JSON snapshots are historical source-owned definitions, not an editable second central registry. Actual bound prerequisite JSON can replace a captured prerequisite definition at admission/build time, pinned to that publication's source commit. The source credential only reads DP; the verified coordinator supplies needed pinned dependency definitions in the target request. The publisher independently fetches/verifies them.

Callbacks carry capture/repository/target/admission intent, source run/attempt/job, artifact ID/digest and publication commit. The source run's actor, event, workflow, repository, attempt, real job and artifact facts must match. The immutable profile/context must match recorded capture facts. ZIP bytes must match the authenticated artifact digest before safe extraction; package bytes must match the artifact manifest before rebasing/signing. Trust remains source-run trust, including wrapper-added jobs, not exclusive-recipe attestation.

## Capacity and recovery

Observed occupied capacity counts all hosted organization jobs with `in_progress` status and allocated runners. Repository/runner/job identities reconcile pending source/publication commitments against actual occupied jobs, including a job that starts between observations. Queued runs/jobs are reported as backlog, never occupied. Self-hosted jobs do not consume this hosted total. Standard x64 and arm64 share the conservative observed total; larger/macOS jobs are conservatively included rather than treated as free. Control itself is already observed, and publication may consume headroom, preventing coordinator self-deadlock.

Unknown observations fail closed for builds and publication. Previously built artifacts remain queued. API endpoints are included in errors. Transient failures (transport, timeout, 5xx, rate limits) and configuration/scope failures are classified and recorded; retry delays are bounded 1–30 minutes. Later wakes retry after the deadline; manual controller dispatch clears it after operator repair. Complete visibility is required before any new capacity-consuming dispatch. Counting and dispatching cannot be atomic against unmanaged work, so two-slot headroom is best-effort only.

Strict cause priority is publication → prerequisite/overlap → tag request, without fairness insertion or preemption. A busy serialized publisher with more ready publication work does not allow a lower priority to bypass it. No work-conserving exception was adopted. Drain reasoning assumes bounded arrivals and retry budgets. Build and publication budgets are independent, three dispatches each; terminal nodes leave the active capture scan and can be explicitly retried.

The controller performs one pass per callback, DP capture/publication completion, manual request or static ten-minute scheduled wake. Idle passes avoid capacity enumeration and capture downloads. Changed/active control work refreshes the existing status projection through its CAS writer, outside package acceptance. Cross-repository unmanaged completion has no native DP `workflow_run` subscription; scheduled recovery is the chosen bounded substitute. Scheduled delays/drops, API propagation and end-to-end latency remain hypotheses pending separately authorized validation.

## Supported overrides and cost

These were included in the approved growth estimate. Costs below are attributable production-line estimates rather than disjoint file totals; common validation is shared.

| Setting | Default / real alternative | Incremental production cost |
| --- | --- | --- |
| Capacity | Plan mapping / explicit integer | ~3 lines plus shared setting validation |
| Headroom | 2 / positive integer | ~1 threshold reference plus shared validation |
| Dependent source | Last-published / max-semver tag from A | ~8 selection lines; same capture path |
| Overlap | Automatic / off for pinned re-admission; fresh captures on new prerequisite events remain enabled (current clarification) | ~4 conditional references around shared readiness/rebinding |
| Shared master loading/validation | Reject unknown fields, matrices, graphs and commands | ~18 lines supporting all settings |

No diamond-bypass override was retained: A/C do not establish an approved contrasted alternative. Priority, per-target flow and work-conserving behavior get no flag. Throughput remains the provisional no-batching/no-time-target interpretation. Backward tag moves retain new captures/revisions without a new policy.

Reduction alone cannot observe unrelated organization work, retain moved-tag pending intent or recover lost dispatch/callback facts. Those additions implement explicit new guarantees and use the existing ledger/writer rather than a second authority. Expected approved system production growth was +450–650; tests were estimated +350–550 (not a hard ceiling). Final measured totals, moved code and verification are in the handover. Moving recipe/test-driver code is counted as moved, not as deleted complexity.

## Research as of 2026-10-20

| Classification | Finding and evidence |
| --- | --- |
| Verified (read-only API) | `gh api orgs/SNodeC`: Free plan, 37 public + 6 private repositories; authenticated inventory contained all 43. A subsequent read-only invocation of the implemented observer successfully examined all 43 repositories and found 0 occupied hosted jobs and no queued backlog (20 free before commitments/headroom). Existing access is not proof that a future observer installation has equivalent visibility. |
| Documented | [Actions limits](https://docs.github.com/en/actions/reference/limits): standard plan totals Free 20, Pro 40, Team 60, Enterprise 500; larger runners have different limits. There is no discovered standard-quota endpoint, so the documented mapping is used. |
| Verified + documented inference | `orgs/SNodeC/actions/hosted-runners/limits` returned unsupported/404 for this Free org; this [larger-runner endpoint](https://docs.github.com/en/rest/actions/hosted-runners) is not a standard-plan quota authority. A combined conservative standard total is used; actual pool behavior has not been measured. |
| Documented | [Workflow runs](https://docs.github.com/en/rest/actions/workflow-runs) and [jobs](https://docs.github.com/en/rest/actions/workflow-jobs): per-repository endpoints, pagination, run attempts and job runner fields. The org-wide `actions/runs` probe returned 404. Running jobs with runner allocation are counted; queued/waiting work is not assumed occupied. |
| Documented + estimated | At 43 repos, one observation normally needs 88 inventory/run-list requests plus one job-list request per distinct active/queued run, extra pagination and execution reconciliation. With six scheduled wakes/hour this remains below ordinary authenticated limits at the observed org size; event bursts and many active runs can exceed that estimate. Truncation/failure is unknown, never zero. |
| Documented | [Workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event) supports `return_run_details` and response `workflow_run_id`, `run_url`, `html_url` with API `2026-03-10`. Live use by this implementation is unvalidated. |
| Documented + verified | [Job context](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#job-context) exposes `job.check_run_id`. Read-only source run `39234594417` had Actions job ID, check-run URL and HTML `/job/` identity all `118000496904`. New-wrapper callback delivery remains unvalidated. |
| Documented | [Artifact API](https://docs.github.com/en/rest/actions/artifacts) exposes artifact `digest` and `workflow_run`; raw ZIP download is verified explicitly. API IDs/digests plus source attempt/job identity and file checksums establish the accepted trust model. |
| Documented | [Concurrency queues](https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/) support `queue: max`, up to 100 queued jobs/runs. The earlier prompt's February date is not the current changelog date. actionlint 1.7.12 lacks that schema entry; only that key and the App-token input schema are excluded. |
| Documented | [Workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) restrict `workflow_run` to the receiving repository's workflows. Scheduled workflow delay/drop/disable behavior prevents a timing guarantee; callbacks + bounded scheduled/manual reconciliation remain required. |
| Verified design / hypothesis | Gates use Git/API execution facts and feed snapshots from Git. Raw URLs are used only for immutable commit-pinned baseline/package bytes, never a moving public permit. API visibility has no measured latency guarantee; missing identities defer/fail closed and ambiguous dispatches reconcile later. |

Credential provisioning/widening/rotation is excluded. The old shared App key has installation authority; per-step token narrowing cannot make it safe to share. Separated notify/capture Apps are scoped to DP; publication verifies the coordinator App actor and operator retry verifies a human collaborator with DP write access, because Actions write cannot be restricted to one workflow; the coordinator owns write authority; the observer needs read visibility across every organization repository and plan metadata. No source credential may write Packages or another product repo. See [setup](setup.md#banner).

## Cutover and remaining external validation

All work is uncommitted in approved task worktrees, leaving canonical checkout changes and PRs #30/#31 untouched. Every registered source must have its JSON on its default branch before new-protocol capture. Historical published commits lacking that file remain served, but cannot become new source-owned builds; explicit config-containing releases bootstrap those rows. Existing A captures must be completed or explicitly dispositioned before an incompatible activation. This is a proposed compatible cutover, not an approved freeze/drain/merge plan.

Separately authorize commit, push, PR mutation, credentials/scope changes, any sandbox creation/validation, workflow dispatch, tag actions and activation. No such action is performed by this task.
