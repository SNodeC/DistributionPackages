# Package workflow tooling

All workflow tooling lives in `coreci/`. The controller owns scheduling, dependency choices and revision allocation. The workers read feed policy from `ci/registry.json` and target definitions and hooks from each registered source's `ci/packages.json`.

The workflow entry points are `python3 -m coreci.build resolve|run`, `python3 -m coreci.publish check-run|resolve|run` and `python3 -m coreci.presentation resolve|run`. The manually dispatched `coreci-prepare-rootfs.yml` workflow runs `coreci.rootfs_image` to prepare checksum-pinned Raspberry Pi OS images.

Build hooks run as uid/gid 1000 in disposable containers with read-only source, recipe and tooling mounts. Trusted preparation installs prerequisites before the hook runs. Hooks receive the SPEC 7.2 environment and no signing or feed-writing credentials. `native_container.package` and `openwrt_container.outputs` emit the package output contract. `versions.versions` is the single version encoder and validator.

The publisher independently checks the manifest and package metadata, signs affected packages and indices, validates the locally served prepared feed, and pushes an orphan-root commit with the exact checkout lease. Public index hashes confirm availability. A matching immutable unsigned-file ledger is a no-op; conflicting ledgers or existing files without a ledger fail before signing.

The feed environment supplies `APT_SIGNING_KEY`, optional `PACKAGES_GPG_PASSPHRASE`, `OPENWRT_USIGN_KEY`, `OPENWRT_APK_KEY` and the feed writer App configuration. The App token is scoped to the selected feed and revoked after the job. Temporary private files are owner-readable and never mounted into validation containers. Only report steps receive `CORECI_CALLBACK_SECRET`.

Publication receipts and the controller's read-only status snapshot feed the shared renderer in `presentation.py`. The status workflow writes presentation files and generation state; publication can render the same presentation in its package commit. Package existence is read from the Git tree. Writers inspect an ambiguous push before retrying and retry confirmed lease conflicts at most five times.

Configure local checks with `cmake -S tests/coreci -B /tmp/codex/build/DistributionPackages/checks`, then run `ctest --test-dir /tmp/codex/build/DistributionPackages/checks --output-on-failure` and `actionlint`. The suite includes real DEB/RPM CPack checks, callback signing and G1–G3 presentation/receipt acceptance. Container and remote publication boundaries use fixtures; these tests dispatch no workflows. Staging acceptance requires the owner's authorization and the production-idle gate.
