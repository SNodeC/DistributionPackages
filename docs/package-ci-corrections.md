# Package CI correction handover

## Current revision-2 handover — local correction verified

The local corrective pass is complete and uncommitted. The final reader-boundary correction uses **+7 net production lines**, taking the system to **+707** against the four original bases. The user approved the requested +710 ceiling and another 20 lines if required; that contingency was not used. Historical ownership now reads only the exact pinned commit's JSON object and package namespace. Selected build definitions retain reserved-metadata and build-schema validation. Both views share one immutable per-process lookup/cache; no second cache, persisted field, credential or mode was introduced.

Final complete verification: **198 tests, 197 passed, zero failures/errors, one environment skip**, exit code 0. The remaining skip is real OpenWrt signing without `usign`/`apk` on PATH. Full product/OS builds and live GitHub behavior are not validated by this run. No external stage was performed. The bootstrap choice remains unapproved and does not block local completion.

The older sections below describe the prior correction snapshot. Their green results and satisfied matrices are historical and are superseded by this current section.

### Workspaces and accounting

All four task worktrees remain on `refactor/repository-owned-package-ci`, at the exact HEAD/base values in the workspace table below. DP changes implement ownership, selection, execution commitments, per-prerequisite replacement selection and tests/docs. No source worktree was changed during this pass; their existing uncommitted work is retained. Canonical checkouts, PR30 and PR31 were not mutated. Remote PR state was not queried in this local-only stage.

| Repository | Production added / removed / net | Tests added / removed / net |
| --- | ---: | ---: |
| DP | +1520 / -1101 / +419 | +3079 / -657 / +2422 |
| snode.c | +184 / -7 / +177 | +0 / -0 / 0 |
| mqttsuite | +143 / -88 / +55 | +0 / -0 / 0 |
| IDP | +63 / -7 / +56 | +0 / -0 / 0 |
| System | **+1910 / -1203 / +707** | **+3079 / -657 / +2422** |

Accounting still includes untracked files, treats `tests/` separately and Markdown as docs, and counts the source OpenWrt driver as production. The original 87 driver lines remain moved code, not deleted complexity. The validation-body extraction within DP is likewise a responsibility change, not deletion of that validation. Formatting alignment remains counted unchanged. The original correction projection was +50, and the separately approved reader correction was estimated at +8; actual costs are +50 and +7 respectively; the physical additions/deletions against Git bases differ from projected edits against the already-uncommitted implementation. New source-file coverage includes RPM, so the touched-file byte set is larger than the earlier snapshot; use the current before/after pair rather than subtracting totals over different sets.

Current accounting: `revision2-reader-final-accounting.json`; exact workspace statuses: `revision2-reader-final-workspaces.json`; file hashes: `revision2-reader-final-files.json`, under the evidence directory. Touched production bytes before → after: DP 138,041 → 177,663; snode.c 785 → 10,457; mqttsuite 26,497 → 29,950; IDP 28,843 → 32,334; system **194,166 → 250,404**. The changed-function return audit covers 24 functions (`revision2-reader-return-audit.json`).

### Implemented boundaries

- **Ownership:** `repository.ownership` resolves each manifest source at its own exact commit. Dependency identities include revision and owned file digests. `dependency_identity`/`binding`, admission/reopen, publication stale checks and retained inventories share that policy. The raw lookup at `ci/repository.py:157` validates the JSON object; selected `definition` at line 165 additionally rejects authored reserved metadata. `ownership` at line 172 independently pins `_commit` from the manifest, ignoring unrelated historical fields.
- **Source reuse:** `reuse` selects and verifies prerequisite files and creates inventories from pinned owners. Native installation consumes that set without a second product classification or a global shell-option change. `sdk_dependency` takes export namespaces from the same facts. APT/RPM staging and RPM signing use pinned owners; OpenWrt reindex receives the actual retained manifest. Source request definitions carry minimal `_commit`/`package` facts for all baseline sources and full definitions for the required closure. A mismatched supplied fact fails before download. The source-side `bind_projects` API fallback is unreachable when GitHub identifies a source repository; it fails instead of reading sibling JSON. No credential was widened.
- **Commitments:** a non-published node with a request holds a commitment exactly while waiting. Local terminal status does not release it. The existing observer reconciles terminal waiting nodes on a copy, preserving scheduling status/reason/category/cause/artifact/budgets. Known queued runs have no timer expiry. Successful post-window no-match releases an unbound intent; uncertain observations retain it and record backoff. Source allocation/completion releases the commitment, with occupied jobs replacing it once. Publisher job allocation is used transiently and cannot overwrite the source artifact's job ID, URL or attempt. Operator retry deliberately releases a commitment and can duplicate a still-queued execution.
- **Selection:** `dependent_source` is called by configure and CAS-fresh prepare. Verified omission or ineligibility permits last-published fallback. Transient errors defer without older source selection or request mutation. Deterministic selected-source failures exclude only affected rows and do not change eligibility. Recovery tests perform a later configure/reserve/prepare and obtain the exact original explicit commit. Newer interleaved requests are selected from fresh state. No new pending ledger is introduced.
- **Replacement and closure:** each prerequisite chooses the greatest revision for that prerequisite, not a cross-project maximum. Stable facts do not reset budgets. Real changes reopen once by default. With overlap off, previously attempted work closes with an explicit re-request reason, including application-only captures without an allocated prerequisite revision; never-admitted blocked work remains distinct. Published and structurally excluded nodes skip identity reopening. Queued execution commitments are retained.
- **Errors:** missing keys, missing iterator matches and malformed typed values are classified in existing node/capture observation handlers; capacity errors remain globally fail-closed with a durable reason. Configuration errors retry after 30 minutes. Optional callback-first recovery (L1b) and capture-rerun gating (L3) were not adopted; their residuals are documented.

The paths setting waiting are admission (true), execution observation (from job/run facts), verified unbound absence (false), expired-artifact rebuild (false) and explicit operator retry (false). Definitive dispatch rejection clears waiting and removes the rejected intent/request; a published receipt is excluded from commitments. No new persistent field, timer, controller, database or cache was introduced.

### Verification and before-fix evidence

The authoritative full-run log for this section is `/tmp/codex/build/snodec/package-ci/revision2-reader-complete-verification.log`. It runs complete DP discovery, actual wrappers, actual source definitions/hooks, actionlint on all four repositories and shell checks even when unittest fails. The run executed **198 tests: 197 passed, zero failures/errors, one environment skip** in 187.392 seconds, with exit code 0. All 15 explicit static/wrapper/workflow checks passed. Exact counts and commands are in `revision2-reader-final-test-results.json` and `revision2-reader-static-and-contracts.json`. The previously failing `test_historical_metadata_outside_ownership_contract_is_not_validated` now passes, including exact-commit provenance, one-fetch caching and continued rejection by the selected-definition view. The environment skip remains real OpenWrt `usign`/`apk` signing; no tool was installed. Real APT/RPM signer fixtures run locally, with the previously documented default RPM database diagnostics. Full product/OS builds and live GitHub behavior were not tested.

The exact full command is the command in the reproducibility section below, with output redirected to that log. Tool versions remain Python 3.14.8, Bash 5.3.15, Git 2.55.0, gh 2.46.0 and actionlint 1.7.12; `revision2-tool-versions.json` records fresh local observations. Explicit compilation/shell/lint commands and individual return codes are retained in the current static/checks JSON. Only the documented three actionlint schema exclusions are used.

Before-fix `revision2-complete-review-checks.log` records the final historical-metadata regression red against the +700 snapshot. `revision2-reader-focused.log` is intermediate: 68 tests, one misplaced new assertion in the schema-only fixture; the assertion was moved into the metadata fixture and all existing assertions were retained. The initial three regressions were run before production editing. Expanded before-fix checks load the exact original modules from saved review evidence, verify their hashes, and execute them in memory. `/tmp/codex/build/snodec/package-ci/revision2-baseline-verified-transport.py` also routes CLI reducer subprocesses through those original modules while retaining actual local bare-Git CAS transport. `revision2-complete-baseline-checks.log` is the authoritative replay log; earlier replays using the current child reducer are superseded for reducer-sensitive claims. The replay executed 29 methods: 23 failed, two errored and four passed (53 failed subtest entries, two errors, no skips). Already-correct guards are ambiguity-window retention, checksum-only reopening, presentation revision decoding and unchanged four-format sibling retention; passing baseline guards are not described as newly reproduced defects. Expanded tests were written later and replayed against the original code; this is not a claim of a different chronological sequence.

A direct focused invocation briefly pointed CI_DEFINITIONS at the fixture. Its original bytes were restored exactly to SHA256 `39e53345fca96c6a4dc5e980413f43f17bf52c8800c80c22ab108940a08d4242`. Subsequent baseline replay and the full runner isolate runtime definitions. `revision2-fixture-restoration.md` records this. Git protocols are restricted to local files, Git/gh remote forms are guarded (including gh download), renderer fixtures stay local and downloads are mocked. This is not a universal HTTP sandbox. Original review evidence is preserved; intermediate failed logs do not validate the current snapshot.

### Current N/L evidence

| Item | State | Evidence |
| --- | --- | --- |
| N1 | Fixed locally | Shared pinned ownership, historical schema/metadata and source reuse tests pass; selected definitions stay strict. Existing four-format sibling and SDK/replay assertions are retained. |
| N2 | Fixed locally | Source/publisher queued, allocation, completion, uncertain lookup/backoff, unbound absence and late binding, operator retry and source-job identity tests in `test_corrective_revision2.py`. Live visibility remains unverified. |
| N3 | Fixed for specified cases | Verified omission/ineligibility, transient before/after reservation, exact-commit recovery, deterministic exclusion and fresh interleaving tests. No offboarding policy chosen. |
| N4 | Fixed locally | Synthetic registered framework/arms/join/tail graph, independent counters, expected revision assertions and one join dispatch with overlap off. |
| N5 | Documented, undecided | Setup/maintainer docs explain fail-closed shared rows, A-first new/moved-tag bootstrap, reviewed migration or defer; no bootstrap performed. |
| N6 | Documented | Cost formula includes terminal waiting reconciliation, at least 217 calls for 43 repos before job/reconciliation pages. Busy-publisher optimization not adopted. |
| L1 | Required part fixed locally; optional part deferred | Node/capture malformed facts and capacity error tests; L1b callback-first behavior unchanged. |
| L2 | Documented/tested locally | 30-minute configuration retry and deliberate operator release of unobservable source/publisher commitments; 404 ambiguity documented. |
| L3 | Deferred optional change | Existing capture rerun residual described; no extra gate or installation change. |
| L4 | Updated | Derived PROJECTS authority, generic dependent wording, per-control capture download wording and stable README onboarding links. Approved historical/workspace records retained. |
| L5 | Updated | Realistic capture-source filtering, pinned JSON fixtures, corrected renderer-test claim, gh/remote guards, no install path and runtime fixture isolation. |

### Concrete boundary references

| Boundary | Code | Regression evidence |
| --- | --- | --- |
| One raw lookup, strict selected view, minimal pinned ownership | `ci/repository.py:157`, `:165`, `:172`, `:302`, `:481`, `:679` | `tests/test_corrective_revision2.py:587`, `:604`; reserved metadata rejection also remains in `test_repository_contract.py` |
| Admission/reopen and transient dispatch facts | `ci/dispatch.py:359` | Failure/blocked stability, checksum-only change and overlap-off cases at `test_corrective_revision2.py:529`, `:542`, `:558`, `:574` |
| Reused files, inventories and SDK exports | `ci/repository.py:488`, `:605`; `ci/build/native.sh` | Exact download/install set, checksum rejection, SDK and source-scope checks at `test_corrective_revision2.py:452`, `:625` |
| Publication own files, stale dependencies, retained siblings/inventories | `ci/publish/publication.py:302` | Unchanged four-format and receipt/SDK assertions in `test_publication_formats.py`, `test_repository_contract.py`, `test_controller.py` |
| Format ownership consumers | `ci/publish/apt.py:17`, `ci/publish/rpm.py:11`, `:43`, `ci/publish/openwrt.py:33` | Four-format sibling rebase and local APT/RPM signer fixtures |
| Commitment observer and operator release | `ci/dispatch.py:303`, `:141` | Source/publisher allocation/terminal/uncertain cases at `test_corrective_revision2.py:287`, `:306`, `:336`, `:354`, `:377`, `:392`; source artifact identity at `:41`; rejected publisher at `:19` |
| Fresh selection and per-prerequisite replacement | `ci/repository.py:191`, `:237`, `:384`; `ci/dispatch.py:359` | Selection cases at `test_corrective_revision2.py:183`, `:203`, `:234`, `:247`, `:660`; chain/diamond at `:89` |

Every ownership consumer uses the pinned policy: dependency fingerprints/binding and admission/reopen; source `reuse` and inventories; native installation (consuming only the selected files); SDK export namespace selection; publication own/stale/sibling checks and merged inventory; and format staging/reindex/signing inventories. Admission and publication still check at separate lifecycle boundaries. The source-side missing-definition API fallback remains unreachable; source jobs receive facts through the existing transient request.

Waiting is set on source admission (`dispatch.py:508`) and publisher admission (`:513`); updated from observed job/run evidence (`:339`); cleared by verified post-window absence (`:317`, `:388`), artifact-expiry rebuild (`:474`), explicit operator retry (`:163`) or definitive dispatch rejection (`:528`). A matching published receipt excludes the node from commitments (`:399`, `:477`). Terminal reconciliation merges execution facts only (`:377`–`:384`). Resetting a node after a real dependency change is guarded by no outstanding waiting commitment (`:402`). Known queued execution is never released by its age or local scheduling status.

| Fresh selection outcome | Result |
| --- | --- |
| No pending request / ineligible / already published | Select row's last-published definition; existing latest/head rules apply only as configured or where no pinned source exists. |
| Pending request valid and supports row | Select exact request SHA and its tag. |
| Pending request valid but verifiably omits row | Fall back to the row's last-published source, or exclude if absent. |
| Pending selected definition transiently unreadable | Defer row, select no older substitute, leave request identity/eligibility/budgets/artifacts unchanged. |
| Pending selected definition deterministically invalid/inaccessible | Exclude affected row with a reason, leave request eligibility unchanged, no older substitute. |
| Last-published selected definition unreadable | Transient defers, deterministic excludes; no third-source substitute. |

Configure and CAS-fresh prepare call the same selector. Recovery is tested through a subsequent configure/reserve/prepare, selecting the same explicit commit; the request's own immutable capture retains that commit for replacement/overlap handling. With overlap off, previously attempted stale work closes with a re-request reason. No new deterministic-policy question arose in the specified cases.

### Agreement groups and acceptance cases

“Satisfied” means tested local behavior, not deployed behavior. All earlier group/case tables below are historical.

| # | Agreement group | Current state | Acceptance case | Current state |
| --- | --- | --- | --- | --- |
| 1 | Ownership/onboarding | Satisfied locally | Release types | Satisfied locally |
| 2 | Per-target rolling flow | Satisfied locally | Published vs pending | Satisfied for specified selection/recovery cases |
| 3 | Last-published pinned rows | Satisfied for specified cases; bootstrap pending | Chain/diamond/checks | Satisfied locally |
| 4 | Explicit overlap | Satisfied locally, including off closure | Matrix validation | Satisfied locally |
| 5 | Chains/diamonds/stale checks | Satisfied locally | Tag moves/overlap | Satisfied locally |
| 6 | Strict cause priority | Satisfied locally | Cause priority | Satisfied locally |
| 7 | Org capacity | Partial: local tests pass, live pool/scope unverified | Capacity | Partial: live behavior unverified |
| 8 | Callback trust/recovery | Satisfied locally; optional L1b unchanged | Callbacks | Satisfied locally |
| 9 | Budgets/lifecycle | Satisfied locally | Budgets | Satisfied locally |
| 10 | Publication guarantees | Partial: real OpenWrt signing skipped | Replay | Satisfied for normal verified receipt fixtures |
| 11 | Credentials | Partial: installation/live separation unverified, L3 residual | Siblings | Partial: local four-format assertions pass, real OpenWrt signing skipped |
| 12 | Defaults/overrides | Satisfied locally | Presentation | Satisfied locally |
| 13 | Docs/cutover | Partial: bootstrap and activation unapproved | Onboarding | Satisfied for supported synthetic registration/integration |
| 14 | Architecture/accounting/isolation | Satisfied locally: +707, no new ledger/state/cache | Configuration | Satisfied locally |

### Remaining stages and cleanup

Live hypotheses remain: GitHub created-filter parsing, return_run_details, queue max/overflow, triggering actors on reruns, callback/observer visibility and rate limits, runner contention, token installation scopes (including publisher reads of every registered source), extended dispatch-input size, real OpenWrt signatures, schedule inactivity disabling, reusable @main/secret cutover order and in-flight A capture disposition. No live timing or throughput claim is made.

N5 remains a separate unapproved choice: A-first JSON-containing commits with new or moved tags (no forced VERSION increment merely to add JSON), a reviewed ownership migration, or defer. Every external stage still needs separate later approval: task commits, pushes, PR mutations/merge, tags, workflow dispatch/rerun or sandbox/live validation, credentials/installation scope/rotation/removal, Packages writes and activation/deployment. No additional checkpoint or external permission is inferred from the local budget approval.

All four task worktrees and all review evidence are retained. Disposable fixture repositories and runtime definitions clean themselves up. New logs, hashes, cost projections, static records and bytecode remain under `/tmp/codex/build/snodec/package-ci`. No additional checkout/branch or canonical source copy was created. Local fixture commits/pushes were the only Git writes to remotes. **Live actions performed: none.**

Local implementation only, 21 October 2026. This supersedes the implementation claims in the initial design/handover, while retaining their original review evidence. No commit, push, tag, PR mutation, workflow dispatch/rerun, Packages write, credential operation, installation, activation or deployment was performed.

## Result and architectural boundary

The correction makes the existing CAS ledger the durable release/admission authority, independent of rendering. Source JSON at selected commits remains the product authority; GitHub execution facts verify callbacks; signed manifests/receipts remain publication facts. There is one bounded controller, no second controller, database, persistent definition cache or new mode flag. Dependency readiness and publication staleness remain separate checks sharing identity policy.

The controller reconciles captures that reserved intent but never durably registered. Their completed failures become ineligible, and successful capture retries re-enable only the matching intent. Selected dependent capture errors are row-local. Default heads are consulted only when there is no selected pinned source. Presentation derives captured/feed facts, including retained rows. One bound dependency graph and one feed snapshot supply readiness, dispatch definitions/provenance and stale comparisons. Optional rendering cannot prevent or conceal mandatory registration failures.

Execution errors are node-local: transient transport/rate-limit failures defer with bounded backoff without consuming publication budget; deterministic build/publication failures close for operator retry; expiry/integrity fails closed. Expired build artifacts re-enter source building; expired immutable captures require a new explicit release. Structural exclusions never reopen. Recoverable blocks depend on changed prerequisite facts. Completed work leaves execution observation and capture downloads; retained ledger history is not pruned because replay/recovery still needs it.

Build and publication dispatch share URL-encoded intent/actor reconciliation. A successful response binds its run. Definitive 4xx closes and releases its commitment. Ambiguous responses retain their commitment through bounded rechecks, then require operator inspection rather than assuming absence proves non-dispatch. Automatic redispatch does not follow a short listing absence. Operator retries can still duplicate an earlier invisible execution; feed identity/staleness checks protect publication, not exactly-once execution.

Actual triggering actors authorize operator operations and publication reruns. Tokens are split by reader/dispatcher/Packages writer roles and requested repository scope; the underlying coordinator private key remains broad. Control uses finite `queue: max`. Source keys never gain Packages or other product write authority. No installation was changed.

## Known bootstrap boundary

Historical published sources without repository JSON cannot supply a build definition under this protocol. If retained sibling ownership cannot be recovered from a pinned definition, publication rejects before signing or feed mutation. It does not guess product ownership from overlapping filename prefixes. A valid unpublished repository's bad head does not block another release; an existing feed lacking ownership information requires a separately reviewed bootstrap/migration step. The test `SiblingFormatsTest.test_unknown_retained_sibling_ownership_fails_before_feed_mutation` covers safe rejection. This is a cutover limitation, not an automatic migration implementation. A compatible proposal is to publish JSON/hook-containing source commits through deployed A before switching protocols, as detailed below.

## Workspaces and ownership

All four approved task worktrees remain on `refactor/repository-owned-package-ci`, with all implementation changes uncommitted and unstaged. HEAD equals the original base in every case:

| Repository | Task checkout | HEAD/base |
| --- | --- | --- |
| DP | `/tmp/codex/checkouts/DistributionPackages/repository-owned-package-ci` | `9f30b2d2cf74c17870da5b1c279f3bf10443b88e` |
| snode.c | `/tmp/codex/checkouts/snode.c/repository-owned-package-ci` | `eb7f48e84712f224a830b28fcc6380a1c4b35214` |
| mqttsuite | `/tmp/codex/checkouts/mqttsuite/repository-owned-package-ci` | `fa7260649d7f8ac3e0632e3dbe9d44e534db7abf` |
| snode.c-idp | `/tmp/codex/checkouts/snode.c-idp/repository-owned-package-ci` | `75db1ef6e5aafc08f4f29e51850b6723c372ccb1` |

DP contains coordinator/workflow/signing-boundary changes, removed central target inventories, source-agnostic build support, docs and regression tests. Sources contain their owned definitions/hooks, thin wrappers and README/AGENTS guidance; mqttsuite/IDP also retain the first-pass formatting-baseline alignment. No source implementation changed during this correction phase. Exact complete `git status --short --untracked-files=all`, remotes and locally recorded default refs are in `/tmp/codex/build/snodec/package-ci/improvement-workspaces.json`.

Canonical checkouts were not written or switched. Observed DP remains `fix/package-job-links` at `04998407350316ad93b49db6f54922b0c104b944`, with its unrelated `docs/maintainers.md` edit. Canonical snode.c remains `fix/package-orchestration` at `d795f95f4b4a82b59bed6ec13df1910d2a0511a4`, clean. Canonical mqttsuite remains master at `fa7260649d7f8ac3e0632e3dbe9d44e534db7abf`, with its unrelated `mqttbridge/config.json` edit. Canonical IDP independently advanced to `2d1ecd2c403553c0547b128efa63f072b27f43df` on main and retains unrelated `.qtcreator`, deployment screenshots and test bytecode; none was changed here. PR30 and PR31 were not mutated. Remote PR state was not refreshed in this correction stage; prior review state must be rechecked before any external stage.

## Diff accounting

| Repository | Production + / − / net | Tests + / − / net | Touched production bytes before → after |
| --- | ---: | ---: | ---: |
| DistributionPackages | +1430 / −1068 / +362 | +2334 / −650 / +1684 | 132,522 → 168,337 |
| snode.c | +184 / −7 / +177 | +0 / −0 / +0 | 785 → 10,457 |
| mqttsuite | +143 / −88 / +55 | +0 / −0 / +0 | 26,497 → 29,950 |
| snode.c-idp | +63 / −7 / +56 | +0 / −0 / +0 | 28,843 → 32,334 |
| **System** | **+1820 / −1170 / +650** | **+2334 / −650 / +1684** | **188,647 → 241,078** |

Accounting includes untracked files and measures physical Git additions/deletions against the original bases, not against the previous local refactor. `tests/` is counted separately; Markdown is documentation; all other config/workflow/tooling files count toward production. The source-owned `ci/package/openwrt-tests.py` remains in the conservative production bucket to match the approved accounting convention. Its 87 original lines were retained from DP, with one added terminal `return None`; they are moved code, not deleted complexity. Product build commands were relocated/reshaped into source hooks; their relocation is included on both sides of the diff, not claimed as pure simplification. The initial +555 total grows by +95, reaching the approved +650 total. No additional architecture beyond the existing ledger/controller was introduced. Consolidations removed duplicate dispatch reconciliation and dependency/skip policy, the configure-only memo, repeated binding computations, redundant profile context and unused reads.

## Verification and reproducibility

The complete final invocation passed **169 tests**, with **0 failures, 0 errors and 1 skip** (170 total, 154.482 seconds). The skipped case is `OpenWrtSigningTest.test_real_ipk_and_apk_index_signatures_and_final_checksums`: `usign`/`apk` are unavailable. No missing tool was installed. Real APT and RPM temporary-key signer fixtures passed. All three actual source wrappers, source JSON/hooks, four actionlint invocations covering nine workflows and twelve shell syntax checks passed. Final exit code: **0**. Log: `/tmp/codex/build/snodec/package-ci/improvement-verified-complete.log`; structured counts: `improvement-test-results.json` in the same directory.

The final command, from the DP task worktree:

```sh
CI_DEFINITIONS="$PWD/tests/fixtures/projects.json" \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:. \
TMPDIR=/tmp/codex/build/snodec/package-ci \
SNODEC_TEST_TOOLING=/home/voc/projects/snodec-control-github \
python3 tests/run_package_checks.py \
  --actionlint /home/voc/projects/drafts/workflow-rename-20261013/lint-tools/actionlint \
  /tmp/codex/checkouts/snode.c/repository-owned-package-ci \
  /tmp/codex/checkouts/mqttsuite/repository-owned-package-ci \
  /tmp/codex/checkouts/snode.c-idp/repository-owned-package-ci
```

The runner executes complete DP discovery before actual source-definition/hook validation, the three actual wrapper files, actionlint across all four repos and shell syntax checks. Failures in unittest do not suppress the remaining checks. `GIT_ALLOW_PROTOCOL=file`, the navigation fixture shim and explicit rejection of GitHub Git/gh transport keep fixtures local; renderer subprocesses use the same guard. This is not a network namespace or a claim that every possible HTTP library is sandboxed. Download tests mock HTTP transport. Worktree status is compared before/after the complete invocation; runtime definitions use a disposable isolated file.

`python3 -m py_compile` was run on all nine Python CI/hook modules (DP eight, snode.c one), with `PYTHONPYCACHEPREFIX=/tmp/codex/build/snodec/package-ci/pycache`; mqttsuite and IDP have no Python CI modules. Explicit compilation also passed for all changed Python files, including tests and the changed IDP formatting configuration; exact file arguments are in `improvement-static-checks.json`. Tool versions: Python 3.14.8, Bash 5.3.15, Git 2.55.0, gh 2.46.0, actionlint 1.7.12. The actionlint exclusions are exactly the documented outdated create-App-token `app-id`/`client-id` schema and `queue` key; no source-wrapper exclusion. Shell checks and AST parsing cover relevant source hooks as well as DP tooling.

`git diff --check` passes DP, snode.c and mqttsuite. IDP reports three terminal blank lines copied byte-for-byte from canonical formatting configs (`.clang-format`, `.clang-tidy`, `.cmake-format.py`); these are retained to preserve the mandated shared baseline, not silently reported clean. The changed Python function return audit found no multiple or nonterminal returns. The source definition fixtures match the three actual source JSON files. Formatting configurations match the canonical files; IDP's existing C++ discovery module intentionally adds tests/examples and excludes supplement/build/checkouts, as recorded in AGENTS. No C++ build was required for these Python/shell/JSON/workflow changes. The RPM fixture emits diagnostics about the unavailable default `/var/lib/rpm` database during header queries; those commands succeed, and signature verification uses its own temporary RPM database. This is recorded as a diagnostic, not an environment skip or a failed signature check. Full product/OS/architecture build matrices were not compiled.

Evidence is kept under `/tmp/codex/build/snodec/package-ci/`: final log, static checks, accounting, workspace record and final file hashes. Earlier failed/intermediate logs are retained, including the snapshot race and invalid build-object isolation reproduced before their corrections. One complete intermediate run exposed a missing ROW_PROJECTS restoration in the new configure test; the fixture now restores that mutable table just like the other configure tests, with its assertions unchanged. Their results do not replace final-snapshot validation. Original `accounting.json`, `verified-files.json`, Claude reviews, self-review probes and evidence remain untouched.

Only this final handover and the bootstrap/testing prose in setup/README/orchestration were finalized after the code/test run; production and test bytes remained unchanged.

## Agreement groups 1–14

“Satisfied” below means verified locally at the cited code/test boundary. “Partial” identifies a material environment/live/bootstrap boundary; it does not assert live operation.

| Group | Status | Evidence and limit |
| --- | --- | --- |
| 1. Ownership/onboarding | Satisfied | `repository.configure/definition/rows`, source JSON/hooks, master validator; `ContractTest.test_master_contains_only_registration_and_real_policy_overrides`, synthetic-repository controller case. |
| 2. Per-target flow/rolling feed | Satisfied | Source-only release, first-target cascade while another root target queues, source finalizer and sibling tests. Workflow propagation remains unvalidated live. |
| 3. Last-published/pinned rows | Partial | Per-row source selection, bad-head isolation and dependent capture mismatch regressions pass. Historical sources without JSON retain the bootstrap limitation above. |
| 4. Explicit overlap/provenance | Satisfied | Newer explicit and same-source/new-revision in-flight cases; provisional capture retry, moved-tag capture and readiness/dispatch snapshot regression. |
| 5. Chains/diamonds/two stale checks | Satisfied | Generic diamond/chain, bound graph and actual publication dependency identity/checksum rejection tests; no full-matrix barrier. |
| 6. Strict cause priority | Satisfied | Three ready classes, busy publisher, limited capacity and multiple captures; no root injection. Drain assumes bounded arrivals/retries. |
| 7. Organization capacity | Partial | Actual observer under mocked all-repository API, queued-vs-allocated/waiting-run, unknown/truncation, commitment/start/terminal and control-headroom tests. Complete credential visibility and live pool behavior unvalidated. |
| 8. Callbacks/trust/recovery | Satisfied | Intake/fork/identity attacks, receive/source attempt/job/artifact checks, bytes/path checks, duplicate/missing/out-of-order and receipt recovery tests. Live callback latency unvalidated. |
| 9. Budgets/lifecycle/state | Satisfied | Separate exhausted budgets, deterministic failure, transient preservation, missing/expired artifact/capture, structural exclusion and unresolved dispatch operator paths; no second reducer/controller. |
| 10. Publication guarantees | Partial | Local CAS conflicts/concurrent writers, replay/no-second-signing, monotonic revision/attempt, stale dependencies, four-format sibling rebase, real APT/RPM signatures and retention checks. Real OpenWrt signatures skipped; historical ownership bootstrap fails closed. |
| 11. Credentials/authorization | Partial | Triggering actor rerun tests, notify rejection, workflow token scopes and DP-only signing secrets checked locally. Installation scope/least-privilege tokens are not provisioned or live-validated. |
| 12. Defaults/overrides/validation | Satisfied | Four known settings, missing defaults, invalid/unknown settings, graph/format/row coverage and numeric OpenWrt validation. Throughput interpretation remains provisional; backward tag moves retain baseline. |
| 13. Presentation/docs/cutover | Partial | Real-job-only links, retained rows and title sanitization tests; READMEs/setup/onboarding/recovery updated. Compatible activation/bootstrap sequence needs separate review and authorization. |
| 14. Architecture/accounting/isolation | Satisfied | +650 total cap, original HEADs, shared policy, per-process immutable lookup only, local bare remotes, offline guard, before/after status check, scoped formatting and separate test accounting. |

## Acceptance cases 1–14

| Case | Status | Evidence |
| --- | --- | --- |
| 1. Release types | Satisfied | `OrchestrationTest.test_source_only_release_does_not_admit_framework`; first-target cascade test. |
| 2. Published vs pending | Satisfied | `ContractTest.test_pinned_per_row_definitions_select_last_published_and_pending_explicit`; newer explicit overlap case. |
| 3. Chain/diamond/checks | Satisfied | `OrchestrationTest.test_diamond_waits_for_all_exact_dependencies_and_publishes_per_target`; bound-graph and publication stale-dependency tests. |
| 4. Matrix mismatch/validation | Satisfied | Intake unsatisfiable row, invalid edges/cycles/families, malformed JSON/matrix, invalid unpublished build-object isolation and release validation cases. |
| 5. Tag moves/overlap | Satisfied | CAS reservation moved-tag/new-source, immutable tag-move capture, genuine stale in-flight same-source/new-revision test. |
| 6. Cause priority | Satisfied | Both priority cases in `ControllerTest`, including occupied publisher and limited capacity; overlap cause tested separately. |
| 7. Capacity | Partial | `CapacityTest` plus controller/recovery headroom, unknown observation, cooldown recovery, commitment reconciliation and terminal release; live org inventory/scope/pool observations unvalidated. |
| 8. Callbacks | Satisfied | `HandoffTest` identity/attempt/job/artifact/duplicate claim tests; node observation recovers missing callbacks and isolates a deleted run. |
| 9. Budgets | Satisfied | Independent publication retry, transient rate-limit preservation, exhausted-budget/operator retry, expiry-driven rebuild. |
| 10. Replay | Satisfied | Conflicting bytes rejected; `RecoveryTest.test_receipt_replay_through_feed_and_git_writer_never_signs_or_writes_feed` verifies no second signing or feed write. |
| 11. Siblings | Partial | All four format rebase fixtures and SDK retained-version case pass. Real OpenWrt signatures unavailable and historical ownership absence safely rejects, not migrated. |
| 12. Presentation | Satisfied | Finalizer/source job URL validation, no invented fallback and retained-row/title tests. |
| 13. Onboarding | Satisfied | Synthetic registered repository with owned definition/integration needs no coordinator production/workflow/inventory edit; exact operator steps in setup. |
| 14. Config | Satisfied | Defaults, supported overrides, invalid unknown fields, rejection of central matrix/graph/commands. |

## Defaults, research and remaining stages

Applied agreements: last-published per row; latest explicit intent ordered by request time/run; finish/discard and automatic overlap re-admission; all in-cascade diamond arms; strict cause priority; no fairness/preemption/root injection; headroom 2; no publication batching or time target (provisional). Missing settings use these defaults. The four supported alternatives remain explicit capacity, integer headroom, latest semver and overlap off. No diamond bypass was added because no agreed evidenced alternative warranted it. Capacity and publication are best-effort; count-then-dispatch is not atomic against unmanaged workflows.

Documented GitHub facts are distinguished from locally verified protocol code:

- [Workflow-run API](https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2026-03-10): active run status filters, pagination/search ceilings and `return_run_details` protocol. Live parsing of our encoded `created` timestamp and returned run details is unvalidated.
- [Concurrency syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency): the queue is finite; live burst/overflow behavior of these workflows is unvalidated.
- [Workflow variables](https://docs.github.com/en/actions/reference/workflows-and-actions/variables): original actor and triggering actor differ on reruns. Local authorization tests cover the distinction; real rerun integration is unvalidated.
- [Actions limits](https://docs.github.com/en/enterprise-cloud@latest/actions/reference/limits): plan-to-standard-concurrency mapping is documented, not a directly observed runner-capacity endpoint. x64/arm64 share our conservative hosted total; larger/macOS jobs are also conservatively charged rather than assumed free. Installation visibility and effective pool limits remain unvalidated.
- [Scheduled events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule): delayed/dropped starts and disabling public-repository schedules after 60 inactive days are documented constraints. Recovery timing, callback propagation, API receipt visibility and runner contention are live hypotheses, not measured SLAs.

With 43 repositories, capacity enumeration uses 217 inventory/initial active-run-list calls plus job pages; cost increases with repositories/active runs. The observer fails closed on unknown data and records a bounded cooldown. One command shares immutable definition fetches by SHA; nothing is persisted as a cache. Successful completed source runs get three receipt-visibility rechecks. An inaccessible node reports its category/reason without preventing independent work; incomplete organization capacity still blocks all new consuming admissions. Publication may use headroom; control does not reserve its own running slot twice.

No measured end-to-end performance or live timing claim is made. Real OpenWrt signatures, narrowed-token installation scope and observer organization/private-repository visibility need an explicitly authorized environment. No missing signer was installed.

The compatible cutover remains a proposal, with each external step separately authorized:

1. Review the four diffs. Stage source JSON and hooks while keeping the old wrappers/protocol active; do not activate the complete local wrapper changes yet.
2. Publish config-containing framework and then explicit dependent source releases **through deployed A**. A's current package commands do not require the new hooks, but its archived/published source identities then contain the definitions needed by the new protocol. Verify every retained row's published source has usable JSON and ownership; do not assume one successful row proves all rows are bootstrapped.
3. Provision and read-only validate separated credentials and observer visibility under separate approvals. Recheck current runs, branch/PR state and installation scope. Inspect/complete or explicitly disposition incompatible A captures before switching protocol; no freeze/drain/merge ordering is approved here.
4. Coordinate DP reusable workflows on `@main`, source wrapper entry points and renamed secrets as one reviewed activation stage. The wrappers must not start using incompatible live reusable interfaces or secrets halfway through the sequence. Old A captures cannot be assumed compatible with the new workflow protocol.
5. Only after separately authorized sandbox/live validation and activation, request new-protocol releases. Preserve rolling feeds, revisions and URLs throughout; no graph-atomic feed replacement is proposed.

This bootstrap proposal avoids inventing legacy coordinator recipes or guessing ownership. Its releases, tags, commits, deployments and any subdivision of the current diffs need explicit later authorization; none was performed here.

Each next external stage needs its own authorization: commit, push, PR actions, tag actions, live workflow tests, sandbox creation/validation, credential provisioning/scope/rotation/removal, Packages writes and activation/deployment. No external stage is inferred from the implementation approval.

## Cleanup and live state

Disposable bare remotes/source fixtures and isolated runtime definitions clean themselves up. Retain the four task worktrees, all original review evidence, new logs/accounting/hashes/static records, the snapshot reproduction and bytecode cache under `/tmp/codex/build/snodec/package-ci` until review/integration; deleting them now would discard uncommitted work or required evidence. No extra checkout, clone or source-tree copy was created during this correction, apart from expressly allowed disposable local bare/source fixtures. Canonical working copies were preserved.

Installation, publication and deployment: **none performed**.
