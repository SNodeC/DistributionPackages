# CI setup and activation

<p>
  <a href="maintainers.md"><img src="media/menu/back-repository-maintenance.svg" alt="← Repository maintenance" width="192" height="24"></a>
</p>

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

The GitHub App needs **Contents: read and write** and **Actions: read-only**. Its installation must cover **snode.c, mqttsuite, DistributionPackages and Packages**. Approve any permission update on the installation after saving the App settings. Artifact transfers use Actions read; dispatches and package/status commits use Contents write. Tokens are scoped per step.

Packages needs no Actions secrets, workflows or build system. Its main branch is written by the publisher, including force-with-lease snapshot replacement. Restrict write access to the publisher and repository administrators.

## Connect upstream releases

The upstream notification workflows target DistributionPackages. Configure the App installation and signing credentials before creating or moving a version tag.

Both upstream projects use the same `Build distribution packages` workflow, with their own project identity. In **each source repository**, set:

| Type | Name | Value |
| --- | --- | --- |
| Variable | `PACKAGES_APP_CLIENT_ID` | The same App client ID as DistributionPackages |
| Secret | `OPENWRT_APP_PRIVATE_KEY` | Existing App private key; retained credential name |

The legacy App credential name does not select a distribution. No package-signing private key is required in either source repository. Keep all three package-signing secrets in DistributionPackages only.

A version-tag push sends `release-tag-changed` to DistributionPackages. That repository captures the release and sends `package-build` to the source repository. Successful source jobs upload unsigned artifacts and send `package-built` back to DistributionPackages. After each SNode.C publication, the publisher sends `package-build` for that target to MQTTSuite, including the exact Packages commit. These dispatches implement one release chain; ordinary commits do not enter it.

Only version-tag creation or movement starts builds. No ordinary push or README change starts package CI. README automation, if present upstream, remains independent. The migration never creates or moves upstream tags automatically.

## Validate and activate

1. Verify all current indexes and their referenced files exist in Packages/main.
2. Verify signing keys match the original feed and configure all credentials above.
3. Verify the two counters in `Packages/status.json` match the last allocated revisions; use zero for a fresh package repository.
4. Review the source scripts and workflow validation results.
5. With explicit approval, connect upstream notifications and exercise a version-tag event.
6. Confirm each target publishes SNode.C before its MQTTSuite build starts, and an application-only event does not rebuild SNode.C.
7. Update devices using the new installer or documented manual repository URLs.

There is no timer or additional Packages workflow. Creation of the new repositories and pushing source files do not trigger package builds. A CI run cannot be claimed validated until it has actually executed with the signing and GitHub App credentials.

Existing device feeds remain on the original URLs until explicitly updated. No redirect, deletion, or change to the original repositories is part of this setup.
