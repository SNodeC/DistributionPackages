# Repository maintenance

[← Installation overview](../README.md)

## Responsibilities

[SNodeC/DistributionPackages](https://github.com/SNodeC/DistributionPackages) owns
recipes, build automation, installation instructions and public signing keys.
[SNodeC/Packages](https://github.com/SNodeC/Packages) holds generated binary
repositories, the public landing page, all documentation, the installer and package status. Both use `main`. No package branch or separate
SNode.C/MQTTSuite recipe branch is required. DistributionPackages can be private;
installation and public documentation depend only on Packages. Source-code,
workflow and settings links in these maintainer guides require access to DistributionPackages.

| Source path | Purpose |
| --- | --- |
| `net/snode.c/`, `net/mqttsuite/` | Canonical OpenWrt Makefiles, feature configuration and installation files |
| `install/install.sh` | Standalone installer for every supported distribution |
| `keys/` | Public signing keys; private keys belong in Actions secrets |
| `ci/targets/` | OpenWrt SDKs, Linux containers and official Raspberry Pi OS images |
| `ci/build/` | Build environments and the upstream OpenWrt CTest launcher |
| `ci/repository.py` | Capture source tags, reuse published dependencies and handle OpenWrt SDKs |
| `ci/publish/` | Signed native indexes, publication, retention and generated status |
| `ci/templates/` | Templates for the generated package READMEs |
| `docs/` | Distribution guides, catalogs and maintenance instructions |

DEB and RPM component definitions remain in the upstream projects' CPack
configuration. The packaging repository does not patch upstream source code.
Device-specific deployment scripts are outside this repository's responsibility.

## Published layout

All paths below are relative to `SNodeC/Packages/main`.

| Distribution | Package files | Repository metadata |
| --- | --- | --- |
| OpenWrt | `openwrt/<series>/<architecture>/` | Signed opkg index or `packages.adb` beside the packages |
| Raspberry Pi OS | `raspberrypios/pool/<suite>/` | `raspberrypios/dists/<suite>/main/binary-<architecture>/` |
| Debian | `debian/pool/<suite>/` | `debian/dists/<suite>/main/binary-<architecture>/` |
| Ubuntu | `ubuntu/pool/<suite>/` | `ubuntu/dists/<suite>/main/binary-<architecture>/` |
| Rocky Linux | `rocky/<major>/<architecture>/Packages/` | `rocky/<major>/<architecture>/repodata/` |
| Fedora | `fedora/<release>/<architecture>/Packages/` | `fedora/<release>/<architecture>/repodata/` |

GitHub tree links browse files. Package managers use raw file URLs, which do not
provide directory listings. OpenWrt development archives support subsequent
MQTTSuite builds against the exact published SNode.C installation.

## Publication model

Only an upstream `vMAJOR.MINOR.PATCH` tag notification starts package CI.
Creating or moving a tag is supported; deleting it is ignored. Pushing ordinary
commits, documentation or generated packages does not start a build.

For a SNode.C release, each target builds and tests SNode.C, publishes it, then
builds MQTTSuite against that target's published SNode.C and publishes MQTTSuite.
For a MQTTSuite release, only MQTTSuite builds, using the target's already-published
SNode.C packages. No target waits for the full matrix to finish.

The captured source bundle freezes the selected tags, resolved commits and
matrix for a run. Tag changes during a build reject a superseded publication.
Publication checks also prevent a build from replacing a newer counterpart.

There are 19 build slots per run. Publications use one serialized writer because
APT architectures share suite metadata and all targets share status and retention
records. A successful build publishes as soon as its writer acquires that lock.

A failed build leaves the previous feed intact. Packages/main is a generated
snapshot: the writer uses a parentless commit and force-with-lease. Source history
in DistributionPackages/main is normal Git history and is never rewritten by CI.
Do not edit generated files manually or protect Packages/main against the writer's
required snapshot replacement.

Superseded files remain for 30 days after leaving the active index. Cleanup runs
on the affected feed during publication, not on an independent schedule. Files
in an idle feed can therefore remain longer. `retention.json` records retirement
and `build.json` records the files currently referenced by signed indexes.

## Workflow entry points

| Workflow | Responsibility |
| --- | --- |
| [release.yml](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/release.yml) | Receive `release-tag-changed` repository dispatches |
| [packages.yml](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/packages.yml) | Capture source releases and expand all targets |
| [package-target.yml](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/package-target.yml) | Order the two projects independently for each target |
| [package-build.yml](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/package-build.yml) | Build one project/target and request publication |
| [package-write.yml](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/package-write.yml) | Update Packages/main using a GitHub App token |

The ordinary workflow token reads this repository and its Actions jobs. A short-lived
GitHub App token, scoped to Packages, writes the separate binary repository.
See [CI setup and activation](setup.md) before connecting upstream notifications.

## Revision numbering

SNode.C and MQTTSuite have independent package revision counters. A SNode.C
release reserves the next number for both projects; an MQTTSuite-only release
advances only MQTTSuite. Numbers are shared across targets of the same project.

Preparation reserves numbers in `Packages/status.json` under the publication
lock before capturing sources. Retries reuse the captured reservation; cancelled
runs leave gaps rather than reusing numbers. Allocation starts above existing
reservations, recorded runs and published project versions. `PACKAGE_REVISION_BASE`
remains a migration floor, not a shared counter. Publication compares revisions
within the affected project. Source versions still come from upstream version tags.

## Coverage and tests

The authoritative target files are [OpenWrt](https://github.com/SNodeC/DistributionPackages/blob/main/ci/targets/openwrt.json),
[Linux](https://github.com/SNodeC/DistributionPackages/blob/main/ci/targets/linux.json) and [Raspberry Pi OS](https://github.com/SNodeC/DistributionPackages/blob/main/ci/targets/raspberrypi.json).
The matrix contains 76 distribution/release/architecture combinations. Presentation
sorts architectures alphabetically without changing the build scheduling order.
Raspberry Pi OS uses an ARMv8-A baseline for Pi 3, 4 and 5, not per-board tuning.

The inherited build scripts run SNode.C's upstream CTests, including through QEMU
for OpenWrt. They build and package MQTTSuite but do not currently invoke an
MQTTSuite CTest suite. This migration does not claim equivalent test coverage or
change upstream production code to introduce it.

## Source records and documentation

Each feed's `build.json` records versions, source tags and commits, checksums and
publication context. APT aggregates architectures within a suite. These records
provide provenance; package and index signatures establish signing authenticity.

[publication.py](https://github.com/SNodeC/DistributionPackages/blob/main/ci/publish/publication.py) copies the authored root README, all `docs/` files and
`install/install.sh` into Packages on every publication. It generates `docs/status.md`,
and badges from [the status template](https://github.com/SNodeC/DistributionPackages/blob/main/ci/templates/package-status.md). Status describes the
latest attempted build; the version describes the available package. The publication
date belongs to the feed and can change when either project publishes.

Guides and package catalogs are handwritten. Keep their architecture tables in
agreement with the target files. Native component names follow upstream CPack;
`snodec-control` contains the configuration tool.

## Signing-key verification

The installer obtains these public keys from Packages/main. Compare both checkouts:

```sh
for key in keys/*; do
  cmp "$key" "../Packages/keys/${key##*/}" || exit 1
done
```

Compute the fingerprints shown in the installation overview:

```sh
usign -F -p keys/snodec-usign.pub
openssl pkey -pubin -in keys/snodec-apk.pem -outform DER | openssl dgst -sha256
gpg --batch --show-keys --with-colons keys/snodec-apt.asc |
  awk -F: '$1 == "fpr" { print $10; exit }'
```

APT and RPM use the same OpenPGP key. The APK fingerprint is SHA-256 of the DER
public key. Keep existing private signing keys when migrating; do not silently
replace the trust identity.

## Branches and history

Use short-lived development branches and merge into main. The predecessor's device
scripts and obsolete branches have not been imported. Its archived development feed
is not a publication destination here.

See the [migration record](migration.md), [historical design notes](history/distribution-packages-plan.md)
and [OpenWrt build guide](openwrt-build.md). Existing repositories remain unchanged.
