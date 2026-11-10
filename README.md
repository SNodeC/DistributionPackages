# SNode.C package workers

This repository runs the trusted GitHub workers for [core-ci](https://github.com/SNodeC/core-ci). The controller owns scheduling and exact prerequisites. The `coreci/` package validates workflow inputs, builds source-owned hooks without root, and publishes verified packages and receipts to [SNodeC/Packages](https://github.com/SNodeC/Packages).

`coreci-build.yml`, `coreci-publish.yml` and `coreci-status.yml` use the feed registry and the participating sources’ committed `ci/packages.json` definitions. Signing and feed-writing credentials remain confined to trusted publication/status jobs. Public package and receipt confirmation uses HTTPS.

The manual `coreci-prepare-rootfs.yml` workflow converts checksum-pinned official ARM64 Raspberry Pi OS disk images into immutable OCI environments; source definitions freeze their registry digests. It does not trigger package builds.

Configure the retained worker and golden presentation tests with `cmake -S tests/coreci -B <build-directory>`, then run `ctest --test-dir <build-directory> --output-on-failure`. Full package-chain acceptance requires separate owner approval.
