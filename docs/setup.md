# CI setup and activation

[← Repository maintenance](maintainers.md)

## Configure DistributionPackages

Set the following **repository** variables and secrets in
[SNodeC/DistributionPackages Actions settings](https://github.com/SNodeC/DistributionPackages/settings/secrets/actions).
Organization-level settings restricted to this repository are also suitable.
No GitHub Environment is used by these workflows.

| Type | Name | Value or purpose |
| --- | --- | --- |
| Variable | `PACKAGES_APP_ID` | ID of the publishing GitHub App |
| Secret | `PACKAGES_APP_PRIVATE_KEY` | The App's private key |
| Variable | `PACKAGE_REVISION_BASE` | Fixed migration floor; see the migration record |
| Secret | `APT_SIGNING_KEY` | Existing ASCII-armored private key for APT and RPM |
| Secret | `OPENWRT_USIGN_KEY` | Existing OpenWrt opkg signing private key |
| Secret | `OPENWRT_APK_KEY` | Existing OpenWrt APK signing private key |

GitHub does not reveal existing secret values through its API. Obtain them from
their original secure storage. Do not commit private keys or place them in logs.

The GitHub App needs **Contents: read and write** and an installation covering
Packages. To reuse that App for upstream release notifications, also grant it
access to DistributionPackages. The writer requests a token scoped only to Packages.

Packages needs no Actions secrets, workflows or build system. Its main branch is
written by the publisher, including force-with-lease snapshot replacement. Restrict
write access to the publisher and repository administrators.

## Connect upstream releases

Do this only after validating the new feed and CI configuration. Until then the
existing upstream notifications continue to target the original repository.

Both upstream projects use the same `Package release tag changed` workflow.
In each upstream workflow, the required destination changes are:

```yaml
# actions/create-github-app-token inputs:
app-id: ${{ vars.PACKAGES_APP_ID }}
private-key: ${{ secrets.PACKAGES_APP_PRIVATE_KEY }}
owner: SNodeC
repositories: DistributionPackages
permission-contents: write
```

The existing dispatch command then targets:

```sh
gh api --method POST repos/SNodeC/DistributionPackages/dispatches --input -
```

Keep its existing strict version-tag validation and JSON payload fields:
`repository`, `ref`, `before`, `after`, and `deleted`. The event type stays
`release-tag-changed`. Set the App variable/secret in each upstream repository or
share them using organization settings. Do not send each event to both old and
new destinations.

Only version-tag creation or movement starts builds. No ordinary push or README
change starts package CI. README automation, if present upstream, remains independent.
The migration never creates or moves upstream tags automatically.

## Validate and activate

1. Verify all current indexes and their referenced files exist in Packages/main.
2. Verify signing keys match the original feed and configure all credentials above.
3. Verify the fixed revision floor exceeds migrated package revisions.
4. Review the source scripts and workflow validation results.
5. With explicit approval, connect upstream notifications and exercise a version-tag event.
6. Confirm each target publishes SNode.C before its MQTTSuite build starts, and an
   application-only event does not rebuild SNode.C.
7. Update devices using the new installer or documented manual repository URLs.

This repository has no timer or manual build entry point. Creation of the new
repositories and pushing source files do not trigger package builds. A CI run
cannot be claimed validated until it has actually executed with the signing and
GitHub App credentials.

Existing device feeds remain on the original URLs until explicitly updated.
No redirect, deletion, or change to the original repositories is part of this setup.
