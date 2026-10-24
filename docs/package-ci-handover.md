> Historical design/handover. Current publisher metadata checks, control-derived indexes, CAS graph validation and key authority are documented in [CI orchestration](ci-orchestration.md). Earlier capture-pinned feed-key copying is superseded.

> Historical design/evidence. Superseded by the canonical first-deployment agreement; current operations are in [setup](setup.md) and [orchestration](ci-orchestration.md).

# Local package CI refactor handover

> The initial implementation below was independently reviewed and corrected. See [the correction handover](package-ci-corrections.md) for the current state, final tests and accounting; original evidence is preserved under `/tmp/codex/build/snodec/package-ci`.

Local implementation and verification are complete. Changes are **uncommitted** on `refactor/repository-owned-package-ci` in the four approved worktrees. No project commit, push, PR mutation, tag action, live workflow dispatch/rerun, credential change, package publication or deployment was performed. Read-only GitHub API research/observation was performed with existing credentials.

## Workspaces and ownership

| Repository | Task worktree | Branch HEAD (unchanged base) |
| --- | --- | --- |
| DistributionPackages | `/tmp/codex/checkouts/DistributionPackages/repository-owned-package-ci` | `9f30b2d2cf74c17870da5b1c279f3bf10443b88e` |
| snode.c | `/tmp/codex/checkouts/snode.c/repository-owned-package-ci` | `eb7f48e84712f224a830b28fcc6380a1c4b35214` |
| mqttsuite | `/tmp/codex/checkouts/mqttsuite/repository-owned-package-ci` | `fa7260649d7f8ac3e0632e3dbe9d44e534db7abf` |
| snode.c-idp | `/tmp/codex/checkouts/snode.c-idp/repository-owned-package-ci` | `75db1ef6e5aafc08f4f29e51850b6723c372ccb1` |

All remotes remain `git@github.com:SNodeC/<repository>.git`. Independent work was based on the actual default branches: DP/IDP main; snode.c/MQTTSuite master. New branch refs belong to the linked canonical repositories; the uncommitted files reside in the task worktrees listed above.

Canonical checkouts were not switched, reset, stashed, rebased or edited. DP remains on `fix/package-job-links` at `04998407350316ad93b49db6f54922b0c104b944` with its unrelated `docs/maintainers.md` edit. Canonical snode.c remains on `fix/package-orchestration` at `d795f95f4b4a82b59bed6ec13df1910d2a0511a4`. Canonical MQTTSuite remains master with its `mqttbridge/config.json` edit. Canonical IDP is `/home/voc/projects/snodec/checkouts/idp-client-guide`, main at the base above, retaining its untracked `.qtcreator/`, deployment media and Python cache. These states were rechecked read-only at handover.

DP PR #30 remains open at `3828c72ee108639b9b29bafd088e812590a20605`; PR #31 remains open at `04998407350316ad93b49db6f54922b0c104b944`. The existing source companion PRs were not changed. This task neither extends those PRs nor incorporates the canonical PR #31 working tree. The new real-job-link behavior is required by this task's contract and remains subject to explicit PR-scope coordination before integration.

## Uncommitted change summary

DP now registers repository names and optional settings, loads pinned source-owned JSONs, captures exact per-row sources, admits by cause with organization-wide capacity/headroom, verifies callbacks and artifact bytes, recovers lost handoffs with bounded wakes/backoff, and signs/publishes centrally. The central target inventories, product build/test branches and unused uploaded tooling tarball have been removed; executable tooling remains pinned to checked Git history. Publication receipts, generic dependency/SDK helpers and OpenWrt reindexing were adopted individually from C; public permits, the 45-minute loop, root injection and shared dispatch budget were not.

Each source now owns `ci/packages.json` and its native/OpenWrt integration. The real definitions validate to 76/76/26 targets, respectively, matching the regression fixture data. MQTTSuite also exports its captured OpenWrt recipe through the generic SDK-export interface. The SNode.C OpenWrt upstream-test driver moved into its repository. Thin wrappers forward separate notify/capture secrets. Publication checks the coordinator App actor; manual retry/recovery and guide publication share one human DP-write authorization check, since a notify App's Actions write permission cannot be limited to one workflow. READMEs, onboarding, setup, maintainer/recovery docs and the [design/research memo](package-ci-design.md) describe ownership and limits.

Applicable source formatting configurations match the canonical baseline. IDP intentionally retains test/example discovery and third-party/build/checkout exclusions in its C++ formatting module. DP has no applicable C++/CMake formatting integration. The copied baseline contains three trailing blank EOF lines in IDP configuration files; these were preserved byte-for-byte rather than inventing another style. Other whitespace checks pass, and the final cross-repository whitespace check excludes only `blank-at-eof`.

## LOC accounting

Physical added/deleted lines include workflows, configuration, CI scripts and their comments; `tests/` is counted separately. Markdown is excluded. Untracked task files are included, so `git diff --stat` alone is insufficient. The moved CI upstream-test driver is classified as CI tooling consistently on both sides.

| Repository | Production added | Production removed | Net production | Test added | Test removed | Net tests |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DistributionPackages | 1293 | 1026 | +267 | 1600 | 644 | +956 |
| snode.c | 184 | 7 | +177 | 0 | 0 | 0 |
| mqttsuite | 143 | 88 | +55 | 0 | 0 | 0 |
| snode.c-idp | 63 | 7 | +56 | 0 | 0 | 0 |
| **System** | **1683** | **1128** | **+555** | **1600** | **644** | **+956** |

Production growth is below the approved +650 ceiling. The test estimate (+350–550) was not a hard cap: +404 lines are explicit test JSON input, leaving +552 executable regression/fixture lines net. Added coverage includes the scheduling/callback ledger, unknown observations and backoff, in-flight overlap, same-source dependency changes, ZIP integrity, onboarding and all-format sibling preservation.

Moved code is not counted as an architectural deletion: the OpenWrt test driver has 87 original physical lines moved DP → snode.c, plus one terminal return. At least 34 substantive product-command lines moved to source hooks (13/8/13 by source, exact text ignoring indentation). Other prerequisite commands and matrix values were split/re-expressed at the source ownership boundary. They are not claimed as eliminated complexity. Formatting-baseline changes are included in the totals.

Production/test file hashes are recorded in `/tmp/codex/build/snodec/package-ci/verified-files.json`; their aggregate SHA-256 is `c23d39ea6240b0acea1d75fa59533c111ba43569f4a51860384acb604425a6da`. `accounting.json` records paths, HEADs and counts. Documentation and ignored runtime files are excluded from this code snapshot.

## Verification and evidence

Tools: Python 3.14.8, Git 2.55.0, Bash 5.3.15, CMake 4.3.4, GnuPG 2.4.9, RPM 6.1.0, GitHub CLI 2.46.0, APT 3.3.3, PyYAML 6.0.3 and actionlint 1.7.12. Tests use local bare repositories, temporary signing keys and mocked GitHub transport. No production key or feed was used. Product C++/OS matrices were not compiled; the local CPack/SDK/signing fixtures exercise their CI boundaries.

Common environment, from the DP task worktree:

```sh
export CI_DEFINITIONS="$PWD/tests/fixtures/projects.json"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=tests:.
export TMPDIR=/tmp/codex/build/snodec/package-ci
export SNODEC_TEST_TOOLING=/home/voc/projects/snodec-control-github
python3 -m unittest discover -s tests -v
```

| Command / log under `/tmp/codex/build/snodec/package-ci/` | Result |
| --- | --- |
| Final full discovery → `verification-final.log` | 135 executed: 134 passed, 1 skipped; 302.390 s |
| `python3 -m unittest test_publication_formats test_idp test_packaging.PackagingTest -v` → `images-final.log` | 22 passed after selecting APT image/architecture metadata per product and target |
| `python3 -m unittest test_controller test_package_pages test_orchestration test_orchestration_review test_handoffs.HandoffTest test_publication_formats test_repository_contract test_idp -v` → `final-boundaries.log` | 77 passed after intake/state/presentation updates |
| `python3 -m unittest test_controller test_idp -v` → `priority-cascade-verification.log` | 22 passed, including per-row flow, all-three-class priority and checksum-only staleness |
| `python3 -m unittest test_controller.ControllerTest.test_publication_retry_has_independent_budget_and_keeps_artifact -v` → `budgets-final.log` | Passed with source budget already at 3 before first publication |
| `python3 -m unittest test_publication_formats -v` → `signing-formats-final.log` | 3 passed, including real APT signatures/by-hash and all-format sibling rebase |
| `python3 -m unittest test_repository_contract test_package_pages -v` → `schema-render-verification.log` | 28 passed, including repository-name validation and real-link rendering |
| `python3 -m unittest test_publication_formats test_repository_contract test_orchestration.OrchestrationTest.test_capture_uses_notified_commit_even_after_tag_move_and_checks_bytes -v` → `imports-final.log` | 12 passed after unused-import cleanup |
| `python3 -m unittest test_orchestration test_orchestration_review test_handoffs.HandoffTest -v` → `capture-final.log` | 27 passed after removing the unused tooling tarball |
| `python3 -m unittest test_repository_contract test_package_pages test_controller -v` → `authority-boundaries-final.log` | 47 passed after sharing operator authorization and restricting publication dispatch |

Final authorization checks also execute the workflow guard against source/coordinator actors and reject bot/read-only operator retries before mutation. The final suite contains **136 unique test cases**. Final full discovery ran 135 cases (134 passed, one environment skip). The subsequent 22-case consumer suite verifies the final APT ownership correction and its new regression: all 136 final cases are covered, **135 passed and one skipped**. This is not claimed as one 136-case run. `test-evidence.json` lists IDs/logs; no final case is missing from the evidence. Intermediate failed logs are retained, and their resolved failures are not presented as final results.

The skipped test is `test_handoffs.OpenWrtSigningTest.test_real_ipk_and_apk_index_signatures_and_final_checksums`: `usign` and `apk` are not on PATH. Their build/cache boundary is tested with mocked tools, opkg index rebasing is real local file processing, and APK reindex transport is mocked. Actual OpenWrt signature execution remains uncovered until those tools are available or an explicitly authorized sandbox is used. The real RPM fixture passes with isolated build/db/temp paths; RPM emits host `/var/lib/rpm` query warnings, but actual package and repomd signatures are verified in its temporary key/database context. Real APT InRelease/Release.gpg verification passes with temporary keys.

`tests/check_package_workflows.py` passed against all three actual task wrapper files. All DP workflows passed actionlint with only these documented schema exclusions:

```sh
/home/voc/projects/drafts/workflow-rename-20261013/lint-tools/actionlint \
  -ignore 'missing input "app-id".*actions/create-github-app-token@v3' \
  -ignore 'input "client-id" is not defined.*actions/create-github-app-token@v3' \
  -ignore 'unexpected key "queue" for "concurrency"'
```

Each actual source wrapper passed actionlint without exclusions. Shell scripts passed `bash -n`, Python files passed AST parsing, source formatting copies were checked against the baseline, and source JSON/build-hook validation matched the regression definitions. Final whitespace checks used `git -c core.whitespace=-blank-at-eof diff --check`, preserving canonical EOF whitespace as explained above. No tests were weakened to conceal a failure: obsolete source-finalizer/dispatch-contract fixtures were ported to the new public control/callback boundaries, and badge expectations include the new explicit unsatisfiable state.

A read-only invocation of the implemented observer with existing authenticated access inspected all 43 org repos: Free plan, 0/20 occupied hosted jobs and zero queued backlog at that observation. It did not admit jobs. This verifies endpoint accessibility for that credential and snapshot, not a future observer App's scope, contention behavior or a guaranteed reservation.

## Acceptance cases

| # | Evidence / limit |
| --- | --- |
| 1 Release types | `OrchestrationTest.test_source_only_release_does_not_admit_framework`; `ControllerTest.test_first_target_cascades_while_another_framework_target_is_still_queued` proves no full-matrix barrier |
| 2 Last-published/newer pending | `ContractTest.test_pinned_per_row_definitions_select_last_published_and_pending_explicit`; `ControllerTest.test_newer_explicit_source_survives_framework_overlap_and_gets_dependent_cause` |
| 3 Chain/diamond and both stale checks | `OrchestrationTest.test_diamond_waits_for_all_exact_dependencies_and_publishes_per_target` includes a three-level chain; IDP publication test separately rejects changed source identity and changed prerequisite bytes at publication |
| 4 Validation/mismatched rows | Graph/schema rejection tests; `ControllerTest.test_capture_intake_marks_missing_prerequisite_row_unsatisfiable` records the dependency reason before build admission |
| 5 Moved tags/overlap | Real local Git tag-move/archive/checksum test, monotonic allocation tests, overlap and same-source/new-revision controller tests |
| 6 Cause priority | `ControllerTest.test_all_three_ready_classes_are_dispatched_in_strict_cause_order`; source-only release remains release cause; no root injection or work-conserving flag exists |
| 7 Capacity | `CapacityTest`, pending/headroom tests, job-start race deduplication, unknown-capacity cooldown/recovery, and read-only 43-repo observation; live contention, pool timing and reservation remain unmeasured |
| 8 Callbacks | `HandoffTest`, ambiguous-dispatch and missing-callback observation tests cover duplicate/delayed/out-of-order reports, cleanup failure and mismatched origin/run/attempt/job/artifact |
| 9 Budgets | Independent source/publication counters, three-build-budget publication regression and operator retry preserving artifacts |
| 10 Replay | Authenticated receipt no-op/conflicting-byte/path tests, plus real RPM retry refusing a second signing operation |
| 11 Siblings | `SiblingFormatsTest` drives the shared publication boundary for APT/RPM/opkg/APK; real opkg rebase and retained SDK-version tests; actual APK signing remains the explicit environment skip |
| 12 Presentation | `PackagePagesTest` and HandoffTest: real source `/job/` links only, no run/coordinator fallback; unsatisfiable gets an explicit badge/state |
| 13 Onboarding | `ControllerTest.test_synthetic_repository_needs_only_registration_definition_and_build_wrapper`; generic SDK product/reindex tests; exact steps in setup docs |
| 14 Configuration | Default/override/unknown-field/master-ownership validation in `ContractTest`; actual source definitions and wrapper files validated |

## Decisions, migration and remaining stages

Approved: four new worktrees/branches; up to +650 production lines; per-row last-published source/JSON; no cancellation, latest explicit request coalescing and automatic overlap rebuild. Defaults applied: plan capacity, headroom 2, published dependent versions, automatic overlap, diamond waits, strict cause priority and per-target publication. No work-conserving extension or diamond override was introduced. Throughput's no-batching/no-target interpretation remains provisional; backward moves retain baseline behavior without a new policy.

Source identity, state transitions, CAS behavior, signature fixtures, row ownership and docs are locally verified. Live `return_run_details` propagation, callback delivery, API/job visibility latency, busy x64/arm64 pool behavior, scheduler delay and recovery latency are hypotheses until separately authorized validation. An API snapshot with no occupied jobs cannot establish those properties.

Proposed compatible cutover: review/commit/push/link new PRs only after separate authorization; provision and validate separated credentials/scopes; place JSONs on all registered default branches; inspect and complete or explicitly disposition old A captures; agree a coordinated new-protocol activation; then authorize config-containing prerequisite and dependent releases. Historical source commits without `ci/packages.json` remain served but cannot be rebuilt under the new contract. The first new capture records source-owned definitions for projection; do not run the new guide renderer on legacy-only state before that bootstrap. Existing counters/feed URLs/keys are retained. This is not approval for C's freeze/drain/merge sequence.

Still requiring separate authorization: commit, push, PR actions, tag creation/movement/deletion, workflow dispatch/rerun, writing Packages, credential provisioning/rotation/revocation/scope changes, sandbox creation or live validation, and activation/deployment. The old shared credential installation has not been corrected merely by changing code/docs. Validated request/capture ledger identity now owns duplicate capture detection; an unverified/failed workflow title cannot suppress a later valid notification. Artifactless callback status remains a hint until the shared GitHub observer reconciles it.

## Cleanup and live state

Temporary fixture/build directories, generated runtime definition snapshots and task-created Python caches are cleaned when safe. Verification logs, hash/accounting/evidence JSON and the four uncommitted task worktrees are retained for review; deleting those worktrees now would discard the implementation. No temporary source checkout was silently discarded. The canonical checkouts remain usable in their original task states.

Installation, publication and deployment: **none performed**.
