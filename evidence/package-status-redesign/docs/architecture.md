<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->
<a id="page-overview"></a>

[![Packages](media/page-banner.svg)](../README.md#project-overview)

# How publication works

## Responsibilities

Product repositories build and test unsigned artifacts. DistributionPackages validates each build identity, signs and publishes its target, and renders these pages. Packages serves the signed feeds and generated public documentation; nothing builds or renders here.

## Latest release, Available and In build

**Latest release** is the source version and allocated package revision from the newest captured release for that project. It changes at capture time, before packages necessarily reach the feeds. The overview links to a separate status page for each project.

**Available** comes from the signed feed's `build.json`. A green current indicator means its source version and revision match Latest release; an amber outdated indicator means they differ. An unsuccessful replacement leaves the available packages intact.

**In build** describes only the latest captured revision: pending, running, awaiting publication, failed, cancelled, skipped or superseded. It becomes `—` once that release is available. A skipped dependent means its dependency did not complete successfully; it is not evidence that the dependent was compiled. Indicators have a legend, alternative text and hover descriptions.

**Published (UTC)** is the available package's publication time, shown as `YYYY-MM-DD HH:MM`. The renderer uses project/revision-specific timeline records or an attributable feed timestamp. A feed timestamp belonging to a different project's publication is not reused. An unrecorded value is `—`; capture time is never substituted.

**Build log** opens the job for In build, or the job that produced Available when no replacement is shown. Historical records may provide only a run URL or no URL. **Packages** opens the feed directory; APT pools share suites across architectures, and signed indexes determine compatible files. Viewing Actions logs may require sign-in.

A SNode.C publication dispatches the dependent MQTTSuite build for that target against the exact published dependency snapshot. Release versions and package revisions remain independent facts.

## Trust and ownership

Signing executes only trusted tooling from the captured DistributionPackages commit. Public documentation is copied from its current default-branch `site/` directory; installer scripts and build/signing tools remain capture-pinned. The same central renderer writes project status pages in product jobs and the publisher. Products report metadata without knowing the Markdown structure.

Feed writes are serialized; concurrent status-only commits are merged under Git leases. Generated README blocks are re-rendered from the resulting state while authored README content is preserved. Package publication uses a parentless snapshot, so repository history is not a package changelog. The signing allow-list remains a deliberate DistributionPackages edit; organization catalog entries do not grant signing rights.

## Source records

The feed's `build.json` records provenance and package inventory; the project status page exposes Build log and Packages links rather than embedding those records. Keep signature verification enabled. [Signing keys](../keys/README.md#page-overview) explains the verification keys.
