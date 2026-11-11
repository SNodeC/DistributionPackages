<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="media/nav/banner-documentation-compact.svg"><img src="media/nav/banner-documentation.svg" alt="Packages — Documentation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Documentation"><picture><source media="(prefers-color-scheme: dark)" srcset="media/nav/up-documentation-dark.svg"><img src="media/nav/up-documentation-light.svg" alt="Up to Documentation" title="Up to Documentation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/account-dark.svg"><img align="right" src="media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/organization-dark.svg"><img align="right" src="media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../README.md#banner" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/repository-dark.svg"><img align="right" src="media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# Repository maintenance

## Responsibilities

[core-ci](https://github.com/SNodeC/core-ci) is the sole scheduling, dependency-selection and revision authority. Its durable MariaDB event store records controller state. [DistributionPackages](https://github.com/SNodeC/DistributionPackages) runs trusted GitHub Actions workers that build unsigned packages in disposable environments, validate artifacts, sign and publish packages, and render public status. [Packages](https://github.com/SNodeC/Packages) serves generated signed repositories, receipts and documentation.

Product repositories own their `ci/packages.json` declarations, build hooks, install rules and CPack components. The controller reads declarations from each repository's actual default branch. Tagged source supplies the product being built; recipe policy comes from its default branch. The workers do not allocate revisions or dispatch downstream builds.

| Authoritative source | Purpose |
| --- | --- |
| [`ci/registry.json`](https://github.com/SNodeC/DistributionPackages/blob/main/ci/registry.json) | Registered repositories, feed policy, worker references and signing-key identities |
| [`ci/targets.json`](https://github.com/SNodeC/DistributionPackages/blob/main/ci/targets.json) | Shared target coordinates, container images, platforms and SDK selections |
| Each product's `ci/packages.json` and `ci/package/` | Package identity, dependency edges, target subset, build dependencies and hooks |
| [`coreci/`](https://github.com/SNodeC/DistributionPackages/tree/main/coreci) | Trusted build, validation, signing, publication and presentation tooling |
| [`status-templates/`](https://github.com/SNodeC/DistributionPackages/tree/main/status-templates) | Public status layout and project presentation |
| [`site/docs/`](https://github.com/SNodeC/DistributionPackages/tree/main/site/docs) | Authored public documentation copied to Packages |
| [`install/`](https://github.com/SNodeC/DistributionPackages/tree/main/install) | Shared installer and project entry points |
| [`rootfs-images.json`](https://github.com/SNodeC/DistributionPackages/blob/main/rootfs-images.json) | Checksummed official Raspberry Pi OS disk-image inputs |

## Workflow entry points

All four workers live in DistributionPackages and use `workflow_dispatch`. Actions use version-tag references. Workers do not chain product builds, and GitHub concurrency groups do not schedule or serialize the package chain; core-ci owns those decisions.

| Workflow | Responsibility |
| --- | --- |
| [`coreci-build.yml`](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/coreci-build.yml) | Resolve a frozen assignment, prepare dependencies, execute the source hook and upload unsigned artifacts |
| [`coreci-publish.yml`](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/coreci-publish.yml) | Verify originating build and manifest, sign, validate, publish and report the result |
| [`coreci-status.yml`](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/coreci-status.yml) | Render public status and synchronize authored documentation |
| [`coreci-prepare-rootfs.yml`](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/coreci-prepare-rootfs.yml) | Manually prepare checksum-pinned Raspberry Pi OS OCI images; does not start package builds |

The controller activates and updates packages through valid semantic-version tag events and reconciliation. It reloads declarations after relevant default-branch pushes, periodically, and through its reload operation. A declaration or prerequisite change can require rebuilds. Do not assume that ordinary default-branch changes are operationally inert.

Build hooks execute as uid/gid 1000 in disposable containers. Trusted preparation installs system build dependencies and the exact selected prerequisite development packages before the hook runs. Source, recipe and tooling inputs are mounted read-only; hooks work on a copied source tree. Hooks receive no signing or feed-writing credentials.

## Revisions and recovery

A unit is a package and target pair. The next revision for its selected semantic version is `max(previous revision for that unit/version, revision_base) + 1`. The controller persists allocations and readiness through its event store. Different targets can therefore have different revisions. `Packages/status.json` counters and repository history are not revision-allocation authorities.

The package declaration's `revision_base` supplies a floor when enrolling or resetting controller state. Before a feed reset or tag move, inventory every previously published revision for the affected source version so rebuilt packages sort above installed ones. Tag changes and production operations require their own authorization.

The single version encoder is [`coreci/versions.py`](https://github.com/SNodeC/DistributionPackages/blob/main/coreci/versions.py). Examples are `2.1.0-123~trixie` for DEB, `2.1.0-123.fc44` for Fedora RPM, `2.1.0-123.el10` for Rocky RPM and `2.1.0-r123` for OpenWrt. Build metadata is dropped; prerelease ordering is encoded for each package format.

Use controller retry/rebuild operations for orchestration recovery. Inspect the assigned build identity, attempt, prerequisites and failure before taking action. Do not replay retired source-repository package workflows or invent a new revision in a worker. If a push outcome is uncertain, inspect the remote result before repeating the mutation.

## Published layout and evidence

Paths below are relative to the Packages default branch. GitHub tree links browse directories; package managers use raw HTTPS file URLs and signed indexes.

| Distribution | Package files | Repository metadata |
| --- | --- | --- |
| OpenWrt | `openwrt/<series>/<architecture>/` | Signed opkg index or `packages.adb` beside packages |
| Raspberry Pi OS | `raspberrypios/pool/<suite>/` | `raspberrypios/dists/<suite>/main/binary-<architecture>/` |
| Debian | `debian/pool/<suite>/` | `debian/dists/<suite>/main/binary-<architecture>/` |
| Ubuntu | `ubuntu/pool/<suite>/` | `ubuntu/dists/<suite>/main/binary-<architecture>/` |
| Rocky Linux | `rocky/<major>/<architecture>/Packages/` | `rocky/<major>/<architecture>/repodata/` |
| Fedora | `fedora/<release>/<architecture>/Packages/` | `fedora/<release>/<architecture>/repodata/` |

Immutable unsigned-file ledgers live at `coreci/published/<target>/<package>_<version>-<revision>.sha256`. Public receipts live at `receipts/<build_id>/<revision>.json` and bind source, packages, dependencies, environment and build/publication evidence. OpenWrt development exports live under `dev/<target>/`. Package ownership uses the longest matching registered package prefix, so `snodec-idp` is distinct from `snodec`.

A repeated publication with matching ledger bytes is a no-op while its files remain available. Conflicting ledger bytes or existing output files without a ledger are rejected. The publisher independently inspects package metadata, signatures and the prepared feed before pushing.

The feed is a generated snapshot: writers create parentless commits with an exact force-with-lease. DistributionPackages source history remains ordinary Git history. Do not manually edit generated feed files or replace the expected publication lease. Writers inspect ambiguous pushes and retry confirmed lease conflicts.

Retention runs during publication for the affected package and target. It retains the two highest encoded package versions and removes older recognized package files and development exports. Unknown development entries are retained and reported. There is no 30-day retirement ledger or independent cleanup schedule.

## Coverage and validation

The current target catalog has 76 entries: 26 native Linux targets and 50 OpenWrt targets. Each product declares its supported subset; the catalog does not imply support for every product. The three new enrollment declarations are restricted to full Linux systems. Raspberry Pi OS uses official ARM64 root filesystems.

Test policy belongs to each source hook. Inspect that hook and its reported results; do not infer that every product runs the same CTest suite. DistributionPackages' local worker tests cover contracts, package metadata, dependency preparation, publication, retention and presentation with disposable fixtures. Remote publication and end-to-end package-chain acceptance are separate checks.

From the DistributionPackages checkout, configure `tests/coreci` into an approved temporary build directory, run its full CTest suite, and run `actionlint`. The documented commands are in [the worker README](https://github.com/SNodeC/DistributionPackages/blob/main/coreci/README.md). These local fixture checks dispatch no workflows.

## Documentation, status and installation

Edit authored public guides in `site/docs/`. The shared [`coreci/presentation.py`](https://github.com/SNodeC/DistributionPackages/blob/main/coreci/presentation.py) renderer copies their exact bytes into `Packages/docs/`, removes obsolete documentation, and renders status from publication receipts and the controller's read-only status snapshot. It does not allocate revisions or authorize builds. Status pages retain the shared documentation-page header.

The status worker and the publisher use the same renderer. A documentation merge changes the source for the next presentation synchronization; a merge alone is not proof that the feed has been updated. Confirm the resulting feed path and contents separately. This enrollment task does not authorize manually dispatching the package chain.

The project installer entry points `snodec.sh`, `mqttsuite.sh` and `snodec-idp.sh` already exist and delegate to `install.sh`. The shared installer supports project/component selection and repository-only preparation through `--prepare`. IDP has no OpenWrt packages. Additional project installers must follow the existing implementation and supported package inventory; registration alone does not implement installation support.

See [the IDP catalog](catalogs/snodec-idp.md#banner), [installation](installation/README.md#banner) and [troubleshooting](troubleshooting.md#banner). The preserved October maintenance document records historical proposals; its retired workflow and counter descriptions are not current instructions.

## Signing trust

Keep existing signing-key bytes. The feed registry identifies the expected GPG, usign and APK public keys; [the public signing-key guide](../keys/README.md#banner) explains verification. Private signing material belongs only to the publication environment and must never enter Git, source hooks, artifacts or logs.

APT and RPM share the configured OpenPGP trust identity. OpenWrt uses the configured usign or APK key. Feed-writing App tokens are scoped to the selected feed. Read-only source/artifact access and signed controller callbacks have separate responsibilities; do not broaden permissions to bypass a failed check.

