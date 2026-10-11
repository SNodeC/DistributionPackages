<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->
<a id="page-overview"></a>

[![Packages](media/page-banner.svg)](../README.md#project-overview)

# How publication works

## Responsibilities

Product repositories build and test unsigned artifacts. DistributionPackages validates each build identity, signs and publishes its target, and renders these pages. Packages serves the signed feeds and generated public documentation; nothing builds or renders here.

## Available versus attempted

An available version comes from the signed feed's `build.json`. The latest attempt comes from `status.json`. An unsuccessful rebuild leaves the older packages available. Package revisions are allocated per project; upstream release versions and package revisions are not interchangeable.

A SNode.C publication dispatches the dependent MQTTSuite build for that target against the exact published dependency snapshot. A failed dependency can leave a skipped dependent placeholder; a later dependency retry appears as waiting, without changing the recorded pipeline state.

## Recorded times and failures

Captured means the source bundle capture, not the triggering tag push. Started, built, changed and published are accepted event times in UTC. Timestamps are retained across metadata lease retries. Older captured tools did not record them, so their pages say “not recorded.” Unknown failure stages are not guessed.

A feed's `published_at` can refer to whichever project last updated it. A project-specific publication time is displayed only when recorded for that project and available revision. Pending, building and built-but-awaiting-publication states are not claims of signed availability.

## Trust and ownership

Signing executes only trusted tooling from the captured DistributionPackages commit. Public documentation is copied from its current default-branch `site/` directory; installer scripts and build/signing tools remain capture-pinned. The same central renderer writes project status pages in product jobs and the publisher. Products report metadata without knowing the Markdown structure.

Feed writes are serialized; concurrent status-only commits are merged under Git leases. Package publication uses a parentless snapshot, so repository history is not a package changelog. The signing allow-list remains a deliberate DistributionPackages edit; organization catalog entries do not grant signing rights.

## Source records

Each [project status page](../status/README.md#page-overview) links to feed records, package directories and build runs. APT pools share suites across architectures; signed indexes determine which files are compatible. GitHub Actions logs may require sign-in even for a public repository. Keep signature verification enabled.
