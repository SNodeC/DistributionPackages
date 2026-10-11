# Package-status redesign evidence

These files are a local projection, not a publication to Packages. The recorded source commit is in `snapshot.json`. Authored installation pages and assets are included so the evidence's document navigation can be reviewed; feed-directory links are deployment-relative and no package binaries are copied here.

## Verified

- All 59 DistributionPackages unit/integration tests passed with local usign, APK and RPM signing tools enabled. Signing tests use disposable fixture keys, not production signing secrets.
- Both project status pages contain 76 architecture rows: 75 current and one outdated. SNode.C Debian sid armhf shows available `2.0.0-5~sid`, cancelled `2.0.0-9~sid`; MQTTSuite shows available `1.0.2-5~sid`, published `2026-10-09 05:05`, skipped `1.0.2-9~sid`.
- Actual GitHub Markdown rendering accepts the circles' `align="absmiddle"`, produces 13 release tables and 380 data cells on each project page, and retains linked navigation images.
- Desktop inspection using GitHub's own page styles: maximum article width 1012 px; widest table 776.44 px; row height 38.39 px; circle ink-center offset from version text approximately 0.019 px. Mobile wrapping and horizontal scrolling are intentionally unchanged and were not redesigned.
- The platforms table matches the published snapshot byte-for-byte.
- Deterministic rendering, publication-job URL persistence, validated target/run/attempt job identity, old-payload run URL fallback, metadata-only README updates, concurrent writers and authored README conflict rejection are covered by tests.
- The canonical renamed opkg key is byte-identical to the previous `snodec-usign.pub`. Publication generates the legacy download copy from that one canonical source. Fingerprints were checked with usign, OpenSSL and GPG.
- SNode.C's `CiWorkflowPathsPolicyTest` passed locally. Each product caller differs by exactly three step-environment additions; existing triggers, run names, concurrency and permissions are unchanged. Bash syntax, Python compilation and Git whitespace checks passed.
- Rendering before/after was measured against the recorded state, using the original renderer and template for the baseline. Seven-run median timings are in `snapshot.json`; this is a local filesystem measurement, not a runner performance guarantee.

## Workflow validation

GitHub documents [`job.check_run_id`](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#job-context), and a read-only lookup of an existing SNode.C job confirmed that its Actions job ID matches its check-run ID. The receiver obtains the job URL from the [Actions jobs API](https://docs.github.com/en/rest/actions/workflow-jobs), after checking the validated run, attempt and exact matrix job name.

Actionlint 1.7.12 reports only its outdated schema warnings for existing `queue: max` and `actions/create-github-app-token@v3` client-ID inputs. No other diagnostics appeared. These constructs were retained rather than changing publication behavior: [GitHub concurrency documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency) documents the queue option, and the [action's documentation](https://github.com/actions/create-github-app-token#inputs) documents the client-ID input. Structural YAML comparison additionally checked the unchanged product callers and matching manual/publication concurrency groups. This is not a claim of clean actionlint output.

## Activation boundaries

No workflows were dispatched, tags moved, default branches renamed, licence files changed, or files pushed to Packages for this change. The new manual workflow must be merged and explicitly requested before it is run. It updates generated status regions, not authored site documents or signing keys; those are distributed by the existing publication path.

Executable packaging tools remain capture-pinned. A fresh capture containing this implementation enables new job-ID handoffs and timeline persistence; old captured tools retain their old behavior and can overwrite the newer generated layout if rerun. Existing in-flight/old payloads without a job ID still validate through the existing run checks and use a run URL. The canonical key filename and key guide also need the updated publication tools; do not rerun an old capture as the activation procedure. No historic job IDs or event timestamps were invented.

The legend intentionally includes shared colors: pending/superseded/not-built and outdated/skipped require their alternative text or hover descriptions for exact state identification. There is no white status text inside the circles; tests check the requested circle palette, dimensions and accessible markup instead of the superseded white-text badge contrast requirement.
