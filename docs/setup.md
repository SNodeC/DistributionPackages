<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="media/nav/banner-documentation-compact.svg"><img src="media/nav/banner-documentation.svg" alt="DistributionPackages — Documentation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Documentation"><picture><source media="(prefers-color-scheme: dark)" srcset="media/nav/up-documentation-dark.svg"><img src="media/nav/up-documentation-light.svg" alt="Up to Documentation" title="Up to Documentation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/account-dark.svg"><img align="right" src="media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/organization-dark.svg"><img align="right" src="media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../README.md#banner" title="DistributionPackages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/repository-dark.svg"><img align="right" src="media/nav/repository-light.svg" alt="DistributionPackages repository" title="DistributionPackages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# CI setup and activation

## Configure DistributionPackages

Set the following **repository** variables and secrets in [SNodeC/DistributionPackages Actions settings](https://github.com/SNodeC/DistributionPackages/settings/secrets/actions). Organization-level settings restricted to this repository are also suitable. No GitHub Environment is used by these workflows.

| Type | Name | Value or purpose |
| --- | --- | --- |
| Variable | `PACKAGES_APP_CLIENT_ID` | Client ID of the publishing GitHub App (from its settings page) |
| Secret | `PACKAGES_APP_PRIVATE_KEY` | The App's private key |
| Secret | `APT_SIGNING_KEY` | Existing ASCII-armored private key for APT and RPM |
| Secret | `OPENWRT_USIGN_KEY` | Existing OpenWrt opkg signing private key |
| Secret | `OPENWRT_APK_KEY` | Existing OpenWrt APK signing private key |

GitHub does not reveal existing secret values through its API. Obtain them from their original secure storage. Do not commit private keys or place them in logs.

The GitHub App needs **Contents: read and write** and **Actions: read-only**. Its installation must cover **snode.c, mqttsuite, snode.c-idp, DistributionPackages and Packages**. Approve any permission update on the installation after saving the App settings. Artifact transfers use Actions read; dispatches and package/status commits use Contents write. Tokens are scoped per step.

Packages needs no Actions secrets, workflows or build system. Its main branch is written by the publisher, including force-with-lease snapshot replacement. Restrict write access to the publisher and repository administrators.

## Connect upstream releases

Configure the App installation and central signing credentials before creating or moving a version tag. Capture and scheduling run in DistributionPackages; unsigned builds run in the source repository through the central reusable workflow.

The upstream projects use thin `build-distribution-packages.yml` entry points with identity taken from the calling repository. In **each source repository**, set:

| Type | Name | Value |
| --- | --- | --- |
| Variable | `PACKAGES_APP_CLIENT_ID` | The same App client ID as DistributionPackages |
| Secret | `OPENWRT_APP_PRIVATE_KEY` | Existing App private key; retained credential name |

The legacy App credential name does not select a distribution. No package-signing private key is required in any source repository. Keep all three package-signing secrets in DistributionPackages only.

A version-tag push sends `release-packages` with its tag, commit and originating workflow run. DistributionPackages validates that notification, captures immutable inputs and allocates revisions. It dispatches `build-packages` to the released project. Source jobs report status and unsigned artifacts back to the coordinator. Each successful signed publication unlocks the ready dependents for that target, using its exact Packages commit. See [CI orchestration](ci-orchestration.md#banner) for the complete contract.
Only version-tag creation or movement starts builds. No ordinary push or README change starts package CI. README automation, if present upstream, remains independent. The migration never creates or moves upstream tags automatically.

## Validate and activate

1. Verify all current indexes and their referenced files exist in Packages/main.
2. Verify signing keys match the original feed and configure all credentials above.
3. Verify the project counters in `Packages/status.json` match the last allocated revisions; use zero for a fresh package repository.
4. Drain all existing captures, builds and publication requests before migrating. Merge the central reusable workflows and coordinator first, then the thin entry points in all three source repositories; do not release during this interval.
5. With explicit approval, exercise a version-tag event.
6. Confirm each target publishes SNode.C before its MQTTSuite and supported IDP builds start, and an application-only event does not rebuild SNode.C.
7. Update devices using the new installer or documented manual repository URLs.

There is no timer or additional Packages workflow. Creation of the new repositories and pushing source files do not trigger package builds. A CI run cannot be claimed validated until it has actually executed with the signing and GitHub App credentials.

Existing device feeds remain on the original URLs until explicitly updated. No redirect, deletion, or change to the original repositories is part of this setup.

## IDP integration

The IDP uses `PACKAGES_APP_CLIENT_ID` and `OPENWRT_APP_PRIVATE_KEY`, matching the existing product workflows. Extend the CI App installation to `snode.c-idp`; the publisher derives its repository token scope from the JSON project registry. Signing secrets stay in DistributionPackages.

Merge the IDP packaging/workflow and this pipeline integration before deliberately creating its initial matching `vMAJOR.MINOR.PATCH` tag. The capture step requires a release tag for every dependent product. Do not trigger a new SNode.C capture between enabling the third project and preparing the initial IDP tag. Ordinary branch pushes do not build packages. A release tag must point to a commit containing the thin workflow entry point, including on maintenance branches; backport the wrapper before tagging. Old source workflows are rejected before allocating revisions.

An IDP release captures only supported native targets and consumes their published SNode.C packages. SNode.C publication dispatches IDP rebuilds for native targets, alongside the existing MQTTSuite chain. OpenWrt retains only its existing products. There are no root-server credentials or automatic machine upgrades in CI.
