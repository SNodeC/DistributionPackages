# Repository maintenance

<p>
  <a href="../README.md"><img src="media/menu/back-installation-overview.svg" alt="← Installation overview" width="170" height="24"></a>
</p>

## Responsibilities

[SNodeC/DistributionPackages](https://github.com/SNodeC/DistributionPackages) owns signing, serialized publication, installation instructions and public signing keys. Release preparation and build workflows execute in [SNode.C](https://github.com/SNodeC/snode.c/actions) and [MQTTSuite](https://github.com/SNodeC/mqttsuite/actions). [SNodeC/Packages](https://github.com/SNodeC/Packages) holds generated binary repositories, the public landing page, all documentation, the installer and package status. Both use `main`. No package branch or separate SNode.C/MQTTSuite recipe branch is required. DistributionPackages can be private; installation and public documentation depend only on Packages. OpenWrt recipes belong to [SNode.C](https://github.com/SNodeC/snode.c/tree/master/supplement/openwrt) and [MQTTSuite](https://github.com/SNodeC/mqttsuite/tree/master/misc/openwrt) in their public source repositories. Canonical source-code, workflow and settings links in these maintainer guides require access to DistributionPackages.

| Source path | Purpose |
| --- | --- |
| `install/install.sh` | Standalone installer for every supported distribution |
| `keys/` | Public signing keys; private keys belong in Actions secrets |
| `ci/targets/` | OpenWrt SDKs, Linux containers and official Raspberry Pi OS images |
| `ci/build/` | Shared distribution adapters invoked by the upstream build workflows |
| `ci/dispatch.py` | Authenticated build/artifact handoffs and exact published dependency selection |
| `ci/repository.py` | Capture source tags, reuse published dependencies and handle OpenWrt SDKs |
| `ci/publish/` | Signed native indexes, publication, retention and generated status |
| `ci/templates/` | Templates for the generated package READMEs |
| `docs/` | Distribution guides, catalogs and maintenance instructions |

DEB and RPM component definitions remain in the upstream projects' CPack configuration. The packaging repository does not patch upstream source code. Device-specific deployment scripts are outside this repository's responsibility.

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

GitHub tree links browse files. Package managers use raw file URLs, which do not provide directory listings. OpenWrt development archives support subsequent MQTTSuite builds against the exact published SNode.C installation.

## Publication model

Only an upstream `vMAJOR.MINOR.PATCH` tag push starts package CI. Creating or moving a tag is supported; deleting it is ignored. Pushing ordinary commits, documentation or generated packages does not start a build.

For a SNode.C release, each target builds and tests in SNode.C and uploads an unsigned artifact. DistributionPackages signs and publishes it, then explicitly dispatches that target to MQTTSuite. MQTTSuite downloads the exact published SNode.C snapshot and uploads its unsigned build for signing and publication. For a MQTTSuite release, only MQTTSuite builds, using the target's already-published SNode.C packages. No target waits for the full matrix to finish.

The captured source bundle freezes the selected tags, resolved commits, upstream OpenWrt recipes and matrix for a run. SNode.C’s development archive includes its recipe; an MQTTSuite build reuses that exact published dependency recipe alongside its own captured source recipe. Tag changes during a build reject a superseded publication. Publication checks also prevent a build from replacing a newer counterpart.

Each source repository has 19 build slots per captured release, including two slots dedicated to slow Linux architectures. GitHub applies the shared account runner limit; concurrency groups do not form a cross-repository slot pool. Feed publications use one serialized writer because APT architectures share suite metadata. Status events run independently in their originating jobs and use Git leases. A publisher merges intervening status-only commits and aborts if any other remote files changed.

A failed build leaves the previous feed intact. Packages/main is a generated snapshot: the writer uses a parentless commit and force-with-lease. Source history in DistributionPackages/main is normal Git history and is never rewritten by CI. Neither DistributionPackages nor Packages maintains a copy of the upstream OpenWrt recipes. Do not edit generated files manually or protect Packages/main against the writer's required snapshot replacement.

Superseded files remain for 30 days after leaving the active index. Cleanup runs on the affected feed during publication, not on an independent schedule. Files in an idle feed can therefore remain longer. `retention.json` records retirement and `build.json` records the files currently referenced by signed indexes.

## Workflow entry points

| Workflow | Responsibility |
| --- | --- |
| [SNode.C packages.yml](https://github.com/SNodeC/snode.c/blob/master/.github/workflows/packages.yml) | Capture version-tag releases, allocate revisions, build/test unsigned packages and request publication |
| [MQTTSuite packages.yml](https://github.com/SNodeC/mqttsuite/blob/master/.github/workflows/packages.yml) | Same lifecycle, using the corresponding published SNode.C dependency |
| [release.yml](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/release.yml) | Validate completed upstream artifacts, sign, publish and dispatch dependent targets |

There are no workflows in Packages. Shared platform scripts have one implementation in DistributionPackages; the source repositories own and execute the build jobs. The central publisher executes only tools checked out from its own Git history at the captured packaging commit, never scripts supplied by an uploaded artifact. Signing secrets exist only in DistributionPackages. OpenWrt index signing and RPM package/index signing happen there after upload; APT metadata is also signed there. Builds need no private signing key.

The GitHub App needs Contents write for dispatch/status/publication and Actions read for cross-repository artifacts. Each step requests a token scoped to its required repositories. See [CI setup and activation](setup.md).

A release capture remains the generation identity across repositories. Uploaded artifact names include the source build attempt. A publisher retry reuses that attempt, not its own workflow attempt; a source build retry reports its new attempt. A dependent application has attempt zero while waiting for its library; its first actual build starts attempt one, independently of any SNode.C retries. Already-published unsigned content is recognized before signing again. Retrying a dispatch uses an existing matching upstream workflow run instead of deliberately starting another build. To retry compilation, use Re-run failed jobs in the source repository; to retry signing or pushing, rerun the failed publication in DistributionPackages.

Each SNode.C publication dispatches its exact Packages commit to MQTTSuite. The application validates the source capture and SNode.C revision before using that dependency. A failed dispatch after a successful publication makes the publication workflow red; rerunning it retries the handoff without replacing the published package.

## Revision numbering

SNode.C and MQTTSuite have independent package revision counters. A SNode.C release reserves the next number for both projects; an MQTTSuite-only release advances only MQTTSuite. Numbers are shared across targets of the same project.

`Packages/status.json` holds the authoritative integer counters at `counters["snode.c"]` and `counters["mqttsuite"]`. Source preparation increments each selected counter once and saves its run allocation with a Git lease. Competing metadata or feed commits cause a fresh read and retry; allocation failure stops preparation before any build can use an unreserved number. Retries reuse that allocation without incrementing; cancelled runs leave gaps. History and feed versions never determine the next number. With both counters at zero, the next SNode.C release allocates r1 for both projects. Reset counters only while CI is stopped and preparing a fresh feed; existing feeds retain protection against older publications. Source versions still come from upstream version tags.

## Coverage and tests

The authoritative target files are [OpenWrt](https://github.com/SNodeC/DistributionPackages/blob/main/ci/targets/openwrt.json), [Linux](https://github.com/SNodeC/DistributionPackages/blob/main/ci/targets/linux.json) and [Raspberry Pi OS](https://github.com/SNodeC/DistributionPackages/blob/main/ci/targets/raspberrypi.json). The matrix contains 76 distribution/release/architecture combinations. Presentation sorts architectures alphabetically without changing the build scheduling order. Raspberry Pi OS uses an ARMv8-A baseline for Pi 3, 4 and 5, not per-board tuning.

The inherited build scripts run SNode.C's upstream CTests, including through QEMU for OpenWrt. They build and package MQTTSuite but do not currently invoke an MQTTSuite CTest suite. This migration does not claim equivalent test coverage or change upstream production code to introduce it.

## Source records and documentation

Each feed's `build.json` records versions, source tags and commits, checksums and publication context. APT aggregates architectures within a suite. These records provide provenance; package and index signatures establish signing authenticity.

[publication.py](https://github.com/SNodeC/DistributionPackages/blob/main/ci/publish/publication.py) copies the authored root README, all `docs/` files and `install/install.sh` into Packages on every publication. It generates `docs/status.md`, and badges from [the status template](https://github.com/SNodeC/DistributionPackages/blob/main/ci/templates/package-status.md). Status describes the latest attempted build; the version describes the available package. The publication date belongs to the feed and can change when either project publishes.

Preparation initializes pending entries before builds become eligible. A build reports running after acquiring its build slot, and publishing, failed or cancelled at its end. The publisher commits its terminal event with the package snapshot. A source finalization job closes its interrupted pending/running targets; successful handoffs stay publishing until the central writer finishes. A failed SNode.C target marks its dependent MQTTSuite target skipped. The publisher reports failures in its own final step. Cancellation is repository-local: already-dispatched publication or dependent runs are separate runs and are not cancelled by cancelling the source run. Newer revisions/attempts win; within one attempt states move forward and terminal states cannot be overwritten. Failed SNode.C builds mark their dependent MQTTSuite build skipped. Status delivery is best-effort and cannot prevent builds from running.

Badges are immutable images under `status/badges/`; the generated table changes which image it references. This avoids stale per-target image contents, but GitHub may still cache the Markdown page. GitHub scheduling and network failures can delay updates; force-cancellation or runner loss can prevent final steps from executing. No polling workflow is used.

Guides and package catalogs are handwritten. Keep their architecture tables in agreement with the target files. Native component names follow upstream CPack; `snodec-control` contains the configuration tool.

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

APT and RPM use the same OpenPGP key. The APK fingerprint is SHA-256 of the DER public key. Keep existing private signing keys when migrating; do not silently replace the trust identity.
