<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="media/nav/banner-documentation-compact.svg"><img src="media/nav/banner-documentation.svg" alt="DistributionPackages — Documentation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Documentation"><picture><source media="(prefers-color-scheme: dark)" srcset="media/nav/up-documentation-dark.svg"><img src="media/nav/up-documentation-light.svg" alt="Up to Documentation" title="Up to Documentation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/account-dark.svg"><img align="right" src="media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/organization-dark.svg"><img align="right" src="media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../README.md#banner" title="DistributionPackages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/repository-dark.svg"><img align="right" src="media/nav/repository-light.svg" alt="DistributionPackages repository" title="DistributionPackages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# CI setup and activation

## Configure DistributionPackages

Use [DistributionPackages Actions settings](https://github.com/SNodeC/DistributionPackages/settings/secrets/actions). Organization settings restricted to the intended repositories are also suitable. No GitHub Environment is used.

| Type | Name | Purpose |
| --- | --- | --- |
| Variable | `PACKAGES_APP_CLIENT_ID` | Coordinator/publisher App client ID |
| Secret | `PACKAGES_APP_PRIVATE_KEY` | Coordinator/publisher private key; DistributionPackages only |
| Secret | `APT_SIGNING_KEY` | Existing ASCII-armored private key for APT and RPM |
| Secret | `OPENWRT_USIGN_KEY` | Existing opkg signing private key |
| Secret | `OPENWRT_APK_KEY` | Existing APK signing private key |

The coordinator App needs **Actions: read and write**, **Contents: read and write**, and implicit metadata access. Its installation covers DistributionPackages, Packages and the registry's source repositories. Tokens are scoped to the repositories and operations needed by each job. Actions write dispatches source and publication workflows; Contents write persists feed transactions. Restrict private-key access to DistributionPackages.

Packages needs no workflows or Actions secrets. Restrict its write access to the publisher and administrators. Existing checksums, signing keys, public URLs and serialized force-with-lease snapshot writes are retained.

## Configure source repositories

Each source wrapper uses two separate limited Apps. Configure these variables and secrets in each source repository:

| Type | Name | Purpose |
| --- | --- | --- |
| Variable | `PACKAGE_NOTIFY_APP_CLIENT_ID` | Notification App client ID |
| Secret | `PACKAGE_NOTIFY_APP_PRIVATE_KEY` | Notification App private key |
| Variable | `PACKAGE_CAPTURE_APP_CLIENT_ID` | Capture-reader App client ID |
| Secret | `PACKAGE_CAPTURE_APP_PRIVATE_KEY` | Capture-reader App private key |

The notification App installation needs **Actions: write** on DistributionPackages and implicit metadata read. The reader App needs **Actions: read** and **Contents: read** on DistributionPackages. Neither App has Packages write permission. Source execution uses its repository token to upload its own artifacts and the reader token to download the central immutable capture. No package-signing key belongs in a source repository.

App creation, installation changes, key provisioning and removal are operator actions. GitHub never reveals stored private-key values; use secure original storage or the App's private-key generation page. Never paste keys into workflow inputs, source files, issue bodies or logs.

The old `OPENWRT_APP_PRIVATE_KEY` represented a broadly privileged App, despite its name. It is no longer referenced by these wrappers. Audit other consumers before removing it; never delete a shared credential solely because these three workflows migrated.

## Ordered activation checklist

1. Freeze release-tag notifications and drain all existing captures, builds and publication requests. Do not move tags during migration.
2. Verify the feed indexes, files, signing keys and revision counters. Preserve existing public URLs and installed clients.
3. Provision the two limited Apps, configure their variables and secrets in every source repository, and verify their installation scopes. Keep central signing secrets unchanged. Approve the coordinator App's Actions-write permission if required.
4. Merge the coordinator PR, then all source-wrapper PRs while releases remain frozen. Contract-1 captures cannot execute through the new controller. Backport the wrapper before tagging older maintenance branches.
5. Audit and remove obsolete broad source keys only after every consumer has switched. Keep the central coordinator key private to DistributionPackages.
6. Validate in a separately approved sandbox: exact dispatch run IDs, queued job discovery, read-only capture downloads, gate fencing, failed and cancelled publication retry, controller continuation and all supported target coverage. Use a test feed and signing keys, not production Packages.
7. Resume releases only after that validation. Monitor the capture, **Coordinate package builds**, individual source jobs and publication receipts. A green capture alone does not prove the release published.

The controller has an hourly recovery schedule and a manual resume input. GitHub can delay schedules; public repositories can have schedules disabled after inactivity. Check that the controller workflow is enabled and use **Run workflow** after outages. Its `retry` input accepts `capture/project/target` for a repaired terminal task; see [CI orchestration](ci-orchestration.md#banner).

## Project integration

Add a registry entry, a project recipe, the standard thin workflow and App access. Native-only projects such as IDP select only supported target families. Untagged dependents are explicitly skipped at capture rather than blocking their prerequisites. Ordinary branch pushes do not start package builds, and no workflow moves tags, installs software or deploys to a server automatically.

Handcrafted deployment choices, root-server credentials and device upgrades are outside package CI. This migration changes neither existing package URLs nor deployed machines.
