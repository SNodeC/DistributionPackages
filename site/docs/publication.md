<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="media/nav/banner-documentation-compact.svg"><img src="media/nav/banner-documentation.svg" alt="Packages — Documentation" width="100%"></picture></p>
<p><a href="README.md#page-overview" title="Up to Documentation"><picture><source media="(prefers-color-scheme: dark)" srcset="media/nav/up-documentation-dark.svg"><img src="media/nav/up-documentation-light.svg" alt="Up to Documentation" title="Up to Documentation" width="160" height="28"></picture></a><a href="https://github.com/SNodeC" title="SNodeC organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/organization-dark.svg"><img align="right" src="media/nav/organization-light.svg" alt="SNodeC organization" title="SNodeC organization"></picture></a><a href="../README.md#project-overview" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/repository-dark.svg"><img align="right" src="media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# How publication works

## Responsibilities

Product repositories build and test unsigned artifacts. DistributionPackages validates each build identity, signs and publishes its target, and renders these pages. Packages serves the signed feeds and generated public documentation; nothing builds or renders here.

## Latest release, Available and In build

**Latest release** is the source version and allocated package revision from the newest captured release for that project. It changes at capture time, before packages necessarily reach the feeds. The overview links to a separate status page for each project.

**Available** comes from the signed feed's `build.json`. A green current indicator means its source version and revision match Latest release; an amber outdated indicator means they differ. An unsuccessful replacement leaves the available packages intact.

**In build** describes only the latest captured revision: pending, running, publishing, failed, cancelled, skipped or superseded. It becomes `—` once that release is available. A skipped dependent means its dependency did not complete successfully; it is not evidence that the dependent was compiled. Indicators have a legend, alternative text and hover descriptions.

**Published (UTC)** is the available package's publication time, shown as `YYYY-MM-DD HH:MM`. The renderer uses project/revision-specific timeline records or an attributable feed timestamp. A feed timestamp belonging to a different project's publication is not reused. An unrecorded value is `—`; capture time is never substituted.

**Build log** opens the job for In build, or the job that produced Available when no replacement is shown. A pending dependent may link to its prerequisite release run before a child job exists; that link is context, not evidence that the dependent was built. Historical records may provide only a run URL or no URL. **Packages** opens the feed directory; APT pools share suites across architectures, and signed indexes determine compatible files. Viewing Actions logs may require sign-in.

A SNode.C publication dispatches the dependent MQTTSuite build for that target against the exact published dependency snapshot. Release versions and package revisions remain independent facts.

## Trust and ownership

Package signatures are created only after validation of the originating build. Public instructions are authored in DistributionPackages and copied here; product repositories report status without owning its page layout. Publication leaves older packages available when a replacement fails. Repository history is not a package changelog; use source records and project releases instead.

## Source records

The feed's `build.json` records provenance and package inventory; the project status page exposes Build log and Packages links rather than embedding those records. Keep signature verification enabled. [Signing keys](../keys/README.md#page-overview) explains the verification keys.
