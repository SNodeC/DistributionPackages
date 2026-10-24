<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="media/nav/banner-documentation-compact.svg"><img src="media/nav/banner-documentation.svg" alt="DistributionPackages — Documentation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Documentation"><picture><source media="(prefers-color-scheme: dark)" srcset="media/nav/up-documentation-dark.svg"><img src="media/nav/up-documentation-light.svg" alt="Up to Documentation" title="Up to Documentation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/account-dark.svg"><img align="right" src="media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/organization-dark.svg"><img align="right" src="media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../README.md#banner" title="DistributionPackages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/repository-dark.svg"><img align="right" src="media/nav/repository-light.svg" alt="DistributionPackages repository" title="DistributionPackages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# CI setup

This is the first deployment of the canonical CI on an empty feed. It does not import earlier packages, runs, revisions or receipts. Product integration belongs to each selected version tag. No old-CI release or intermediate trigger is required.

## Credentials

Provisioning and rotation are operator stages, separate from code changes. Verify the actual installation access; a 403 is unknown, not proof that a secret or installation is absent.

| Authority | Installation / token use |
| --- | --- |
| Coordinator App (`PACKAGES_APP_CLIENT_ID`, `PACKAGES_APP_PRIVATE_KEY`) | Installed on the coordinator, allowed sources and feed. The private key has the installation's full authority and stays in the coordinator. Capture/publisher readers request Actions:read and Contents:read; control requests Actions:write and Contents:read only for coordinator/sources. Separate feed-only tokens request Contents:write. |
| Source notify App (`PACKAGE_NOTIFY_APP_CLIENT_ID`, `PACKAGE_NOTIFY_APP_PRIVATE_KEY`) | Actions:write on the coordinator only; no feed or sibling access. It can still cancel coordinator runs or delete their artifacts. |
| Source capture reader (`PACKAGE_CAPTURE_APP_CLIENT_ID`, `PACKAGE_CAPTURE_APP_PRIVATE_KEY`) | Actions:read and Contents:read on the coordinator only. Used by both notification and build wrappers, including private-coordinator checkout. |
| Observer (`PACKAGES_OBSERVER_TOKEN`) | Read organization metadata/plan and Actions in **every** organization repository, including private repositories. No source or feed write authority. API/listing failures and known count mismatches fail closed; optional private-repository counts are not required. |
| Source workflow `GITHUB_TOKEN` | Own-repository contents/actions reads as needed. No Packages write or signing keys. |

Source wrappers forward the notify and capture-reader secrets separately. Coordinator signing secrets are `APT_SIGNING_KEY`, `OPENWRT_USIGN_KEY` and `OPENWRT_APK_KEY`. Per-step narrowing does not narrow the authority of anyone holding an App private key. The coordinator key is broad; never distribute it to sources. No installation or credential change is performed by local tests.

## Repository configuration destinations

Use repository-level Actions variables and secrets, not environment entries. Store the complete PEM text for App keys. Never put secret values in version-controlled files. Keep a protected local backup when generating a credential; GitHub does not return existing Actions secret contents.

| Repository | Variables | Secrets |
| --- | --- | --- |
| DistributionPackages | `PACKAGES_APP_CLIENT_ID` (coordinator App Client ID) | `PACKAGES_APP_PRIVATE_KEY`, `PACKAGES_OBSERVER_TOKEN`, existing `APT_SIGNING_KEY`, `OPENWRT_USIGN_KEY`, `OPENWRT_APK_KEY` |
| snode.c, mqttsuite, snode.c-idp | `PACKAGE_CAPTURE_APP_CLIENT_ID` (reader App Client ID), `PACKAGE_NOTIFY_APP_CLIENT_ID` (notify App Client ID) | `PACKAGE_CAPTURE_APP_PRIVATE_KEY`, `PACKAGE_NOTIFY_APP_PRIVATE_KEY` |

Each of the three sources uses the same reader App values and the same notify App values. The coordinator App private key stays only in DistributionPackages. Use the Client ID from the App settings, not the numeric App ID. All three Apps may use `https://github.com/SNodeC/DistributionPackages` as their homepage; disable webhooks and user OAuth authorization for this installation-token-only integration.

The coordinator App has repository Actions and Contents read/write permissions, installed only on DistributionPackages, the three sources and Packages. The capture-reader App has Actions and Contents read permissions on DistributionPackages only. The notify App has Actions write permission on DistributionPackages only. Metadata read is mandatory. No organization permissions are needed for these Apps.

Create the fine-grained observer PAT with resource owner SNodeC, **All repositories**, repository Actions read-only and organization Plan read-only (Metadata read is automatic). The observer must see every organization repository, not only package products. With selected-repository access, private repositories outside that selection are invisible; the coordinator cannot infer missing private repositories when optional counters are absent. Record its expiry and renewal owner. Do not grant write permissions merely to obtain optional private-repository counts.

The independent `Book-*` verification workflow in snode.c uses `BOOK_COMPANION_APP_CLIENT_ID` and `BOOK_COMPANION_APP_PRIVATE_KEY`. Preserve that separate integration when retiring package-CI credentials; do not distribute the new coordinator private key for it. Verify remaining consumers before removing any old App installation or secret.

## Add a repository

1. Add its basename to `ci/projects.json`. This permits it; it does not activate it.
2. In the source, commit `ci/packages.json`, root `VERSION`, packaging/build hooks and the thin `build-distribution-packages.yml` wrapper. Copy the wrapper interface from an existing source and point its reusable-workflow literal to this deployment's coordinator/ref. No coordinator production code, workflow or central target-list change is needed for supported platforms.
3. The JSON contains `title`, unique `package` namespace, `depends_on`, `matrix`, and `build` hook paths. Use existing source JSONs as complete examples. Dependencies reference allowed repository basenames. Definitions are validated for cycles, capabilities, safe hooks and row coverage. The source selects its distro/release/architecture rows; DP has only generic capabilities.
4. Hooks run from the captured tag archive. A native hook runs in the target environment with `BUILD_PROJECT`, `DISTRIBUTION`, `SUITE` and `PACKAGE_RELEASE`, writes `packages/`, and emits `<package>.packages` listing component names. It may use the optional CPack helper or its own build system. Debian/RPM metadata must match the pinned namespace, target and tag/revision version. OpenWrt hooks supply their SDK recipe and may use the generic SDK export/import contract. Signing never runs in source hooks.
5. Grant the separated reader/notify access and validate the actual wrapper, JSON and hook contracts locally.
6. The user creates or moves a strict `vMAJOR.MINOR.PATCH` tag, with no leading zeros, whose commit contains this integration and matching `VERSION`. The wrapper transmits the full JSON and exact source identity. Verified intake durably records activation and the pinned definition before building. A failed first build **keeps** activation.

OpenWrt hooks must not replace imported prerequisites during compilation. Suppress imported prerequisite compile targets
(`package/feeds/package_ci/<dependency>/compile`) when supplying the hook's `make` command. The coordinator repeats the
existing import conflict check after compilation: changed bytes or links fail; missing ordinary files are restored.
This is a cooperating-hook integrity check, not proof that no byte-identical rebuild occurred.

Until step 6, the product contributes no graph or target rows and is not discovered merely because tags exist. Never substitute a default branch for a missing tag. A direct application release with missing matching published prerequisites closes those rows with a clear reason; other rows proceed. A later prerequisite publication can cascade to that now-active product at its highest semantic tag. Each application's own first notification is required.

## Deploy for another organization

Use the identical coordinator production code. Configure allowed source basenames and optional `feed.repository`/`feed.branch` in `ci/projects.json` (defaults `Packages`/`main`). Supported settings are `capacity` (`plan` or an integer), `headroom` (default 2), and `rebuild_overlap` (default true). Unknown keys fail; `dependent_version` is removed because cascades always select the highest semantic tag.

Coordinator identity is derived from its own checkout/workflow identity; called workflows use `job.workflow_repository` and `job.workflow_sha`, rather than the caller's repository. Token repository lists, URLs and workflow guards derive from that identity and the master config. Change only deployment configuration, `site/` and installer content, public keys, credentials and the GitHub-required reusable-workflow literals in source wrappers. Build hooks can be non-CMake.

The supported model is one GitHub.com organization with coordinator, sources and a public feed under that owner. Cross-owner sources, personal-account plan observation, GitHub Enterprise Server and private-feed download authorization are not implemented. The repository has not been extracted into a separate CI project.

## First-deployment rollout

This is a runbook, not authorization to perform these operations.

1. Review the locally verified diffs. Commit/push/update the existing task PRs under the user's stage authorization.
2. Provision and verify separated credentials as a separate operator stage.
3. Stop old writers: confirm no old runs, schedules or old-protocol wrappers can write the feed. Dispose of in-flight old captures; they are not reusable by this protocol.
4. Initialize the fresh feed in one reviewed **normal commit**, as a separate destructive stage. From a local feed checkout at the live HEAD, `git ls-files -z` gives the concrete delete list. Remove every tracked old-feed path, then create only `status.json` with the exact JSON below. `.git/` is never removed. `retention.json`, keys, indexes, guides and status pages are created by canonical publication/rendering. Review `git diff --stat`, `git diff --name-status` and the new file before committing. Do not force-push or rewrite history for this initialization.
5. Merge DP after initialization, because its schedule and workflow-completion wakes become active on merge. Then merge all source integrations. Confirm their reusable references and secret names agree.
6. The user tags/moves `snode.c` first, then each application's own tag to activate it. The agent performs no tag operation or manual workflow dispatch.

For this deployment, initial `status.json` is:

```json
{"repository":"SNodeC/Packages","branch":"main","counters":{},"allocations":{},"requests":{},"runs":{}}
```

For another deployment, substitute its configured feed identity/branch. A scheduled control pass with this content is a safe no-op. To generate the concrete fresh-feed diff locally, after reviewing the tracked delete list:

```sh
git ls-files -z | xargs -0 -r git rm --
printf '%s\n' '{"repository":"SNodeC/Packages","branch":"main","counters":{},"allocations":{},"requests":{},"runs":{}}' > status.json
git add status.json
git diff --cached --stat
git diff --cached --name-status
```

Revision allocation restarts at r1. Installations from the old feed may consider a same-version package with a lower revision a downgrade; there is no compatibility or migration mitigation. Canonical feed publication retains its existing parentless snapshot/CAS writer behavior; the initialization itself is a normal parented commit.

Cascade captures never activate a repository or overwrite its direct notification. Activation after a framework publication yields the requested application build, without a second unsolicited cascade. Older-version framework bug fixes publish normally and initiate no dependent work. An app that failed for missing prerequisites recovers through one highest-tag cascade after the prerequisite publishes. A failed selected diamond arm must be repaired/retried before the join can proceed; inspect its ledger reason.

The observer PAT must use **All repositories** for the organization, including
current and future private repositories. **Only select repositories** hides any
private repository not explicitly selected, including its running jobs. That
would cause capacity undercounting and extra admission/queueing. The product
allowlist is unrelated to this organization-wide observer scope. GitHub may
omit private-repository counts; successful complete pagination is accepted
under this operator-verified scope requirement. Counts are cross-checked when
provided. Changing the token's repository selection requires rechecking this
requirement. No write permissions are needed for observation.

Public signing keys are deployed through the coordinator default-branch overlay; the captured key for the signing family must match. Follow the [key authority and operating limits](ci-orchestration.md#public-key-authority-and-operating-limits) for authorized rotation and fresh captures. Do not remove an allowlisted repository with requests; offboarding is not implemented.
