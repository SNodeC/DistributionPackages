# SNode.C package workers

This repository runs the trusted GitHub workers for [core-ci](https://github.com/SNodeC/core-ci). The controller on vchrist owns selections, exact prerequisites and committed assignments. These workers validate those assignments, build source-owned hooks without root, and publish verified packages to [SNodeC/Packages](https://github.com/SNodeC/Packages).

The participating sources are SNode.C, MQTTSuite and SNode.C IDP. Their committed `ci/packages.json` files own the 76, 76 and 26 target definitions and dependency declarations.

The package dashboard is http://core.vchrist.at:8081/. Static package status retains the existing [SNode.C presentation](https://github.com/SNodeC/Packages/blob/main/status/snodec.md#banner). Its updater reads one initial snapshot from that dashboard's existing SSE endpoint, then disconnects. It is not another live page or scheduling authority.

Source artifact validation uses the read-only capture App. Signing and feed-writing credentials remain confined to trusted publication/status jobs. Every feed writer shares the existing GitHub concurrency group. Public package and receipt confirmation uses HTTPS.

The manual Raspberry Pi preparation workflow converts the two checksum-pinned official ARM64 disk images into immutable OCI environments; source definitions freeze their registry digests. It does not trigger package builds.

Run `python3 tests/worker.py` for isolated SSE/presentation and real DEB/RPM component checks. Full package-chain acceptance requires separate owner approval; no release tag is implied by setup.
