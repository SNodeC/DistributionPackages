<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="media/nav/banner-documentation-compact.svg"><img src="media/nav/banner-documentation.svg" alt="Packages — Documentation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Documentation"><picture><source media="(prefers-color-scheme: dark)" srcset="media/nav/up-documentation-dark.svg"><img src="media/nav/up-documentation-light.svg" alt="Up to Documentation" title="Up to Documentation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/account-dark.svg"><img align="right" src="media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/organization-dark.svg"><img align="right" src="media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../README.md#banner" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/repository-dark.svg"><img align="right" src="media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# How publication works

## Responsibilities

Product repositories build and test unsigned artifacts. DistributionPackages validates each build identity, signs and publishes its target, and renders these pages. Packages serves the signed feeds and generated public documentation; nothing builds or renders here.

## Latest release, Available and In build

**Latest release** is the highest source semantic version requested or captured for that project. It has no project-wide revision label because rows can have different package revisions. It changes at capture time, before packages necessarily reach the feeds. The overview links to a separate status page for each project.

**Available** describes that same highest semantic version in the signed feed's `build.json`. If it has never published, Available is `—`; an older success is not substituted. The package version is shown plainly, without Current/Outdated icons. An unsuccessful replacement leaves the available packages intact.

**In build** retains the existing pending, building, publishing, failed, cancelled, skipped, superseded, not-built and unsatisfiable indicators. It also shows Waiting for or Blocked with links to immediate prerequisites, including indirect diamond waits before a new capture exists. Prerequisite pages explain upstream waits. A wait implies no new revision or job. Direct pending builds retain their presence-only policy. A centered `—` means no recorded replacement or prerequisite activity remains; labels are left aligned. Missing prerequisites fail affected rows clearly; this does not activate or build a prerequisite implicitly. Indicators have a legend, alternative text and hover descriptions.

**Published (UTC)** is the available package's publication time, shown as `YYYY-MM-DD HH:MM`. The renderer uses project/revision-specific timeline records or an attributable feed timestamp. A feed timestamp belonging to a different project's publication is not reused. An unrecorded value is `—`; capture time is never substituted.

**Build log** opens the job for In build, or the job that produced Available when no replacement is shown. Only a verified source-job URL is linked. Before a source job exists, no log link is shown; a capture or coordinator run is never substituted. **Packages** opens the feed directory; APT pools share suites across architectures, and signed indexes determine compatible files. Viewing Actions logs may require sign-in.

A prerequisite publication cascades to active dependent repositories at their highest semantic-version tags, per matching target. Each source activates through its own first valid tag notification and owns its matrix/JSON at that commit. Direct tag builds use the exact requested version, even when older. Older direct builds still sign/publish without changing any highest-version status field or timestamp. Supported versions coexist in the same feed, one published revision per version. Release versions and package revisions remain independent facts. Matching cascade captures can share revisions across rows, but different histories or prerequisites may still diverge them; each row shows its actual package version. Sharing describes reservation-time release provenance, not equal package bytes or later pinned rebuild inputs.

## Trust and ownership

Package signatures are created only after validation of the originating build. Public instructions are authored in DistributionPackages and copied here; product repositories report status without owning its page layout. Publication leaves older packages available when a replacement fails. Repository history is not a package changelog; use source records and project releases instead.

## Source records

The feed's `build.json` records provenance and package inventory; the project status page exposes Build log and Packages links rather than embedding those records. Keep signature verification enabled. [Signing keys](../keys/README.md#banner) explains the verification keys.
