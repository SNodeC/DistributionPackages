<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="media/nav/banner-documentation-compact.svg"><img src="media/nav/banner-documentation.svg" alt="DistributionPackages — Documentation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Documentation"><picture><source media="(prefers-color-scheme: dark)" srcset="media/nav/up-documentation-dark.svg"><img src="media/nav/up-documentation-light.svg" alt="Up to Documentation" title="Up to Documentation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/account-dark.svg"><img align="right" src="media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/organization-dark.svg"><img align="right" src="media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../README.md#banner" title="DistributionPackages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="media/nav/repository-dark.svg"><img align="right" src="media/nav/repository-light.svg" alt="DistributionPackages repository" title="DistributionPackages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# Repository maintenance

## Responsibilities

[SNodeC/DistributionPackages](https://github.com/SNodeC/DistributionPackages#banner) owns signing, serialized publication, installation instructions and public signing keys. Release preparation and build workflows execute in [SNode.C](https://github.com/SNodeC/snode.c/actions) and [MQTTSuite](https://github.com/SNodeC/mqttsuite/actions). [SNodeC/Packages](https://github.com/SNodeC/Packages#banner) holds generated binary repositories, the public landing page, published documentation, the installer and package status. Authored public documentation belongs to DistributionPackages/site; default branches are read from the GitHub API. No package branch or separate SNode.C/MQTTSuite recipe branch is required. DistributionPackages can be private; installation and public documentation depend only on Packages. OpenWrt recipes belong to [SNode.C](https://github.com/SNodeC/snode.c/tree/master/supplement/openwrt) and [MQTTSuite](https://github.com/SNodeC/mqttsuite/tree/master/misc/openwrt) in their public source repositories. Canonical source-code, workflow and settings links in these maintainer guides require access to DistributionPackages.

| Source path | Purpose |
| --- | --- |
| `install/install.sh` | Standalone installer for every supported distribution |
| `keys/` | Public signing keys; private keys belong in Actions secrets |
| Source `ci/packages.json` | Repository-owned targets, dependencies and build hooks |
| `ci/build/` | Shared distribution adapters invoked by the upstream build workflows |
| `ci/dispatch.py` | Authenticated build/artifact handoffs and exact published dependency selection |
| `ci/repository.py` | Capture source tags, reuse published dependencies and handle OpenWrt SDKs |
| `ci/publish/` | Signed native indexes, publication, retention and generated status |
| `ci/templates/` | Templates for the generated package READMEs |
| `site/` | Authored public README, guides and media; `docs/` holds maintainer instructions |

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

For a SNode.C release, each target builds and tests in SNode.C and uploads an unsigned artifact. DistributionPackages signs and publishes it, then admits matching registered dependents on that target using their pinned definitions. MQTTSuite downloads the exact published SNode.C snapshot and uploads its unsigned build for signing and publication. For a MQTTSuite release, only MQTTSuite builds, using the target's already-published SNode.C packages. No target waits for the full matrix to finish.

The captured source bundle freezes the selected tags, resolved commits, upstream OpenWrt recipes and matrix for a run. SNode.C’s development archive includes its recipe; an MQTTSuite build reuses that exact published dependency recipe alongside its own captured source recipe. Moved tags do not change captured source bytes. New explicit requests coalesce by request time; dependency changes reject obsolete output and cause automatic rebuilding by default. Publication preserves unrelated newer siblings.

Admission counts all observed hosted organization jobs against the plan-derived limit, with default headroom two for control and publication. Per-source concurrency groups are not a global capacity authority. See [CI orchestration](ci-orchestration.md#banner) for occupied jobs, pending commitments, strict cause priority and unknown-observation handling. Feed updates remain serialized; CAS writers preserve unrelated status/feed/authored-documentation updates.

A failed build leaves the previous feed intact. Packages/main is a generated snapshot: the writer uses a parentless commit and force-with-lease. Source history in DistributionPackages/main is normal Git history and is never rewritten by CI. Neither DistributionPackages nor Packages maintains a copy of the upstream OpenWrt recipes. Do not edit generated files manually or protect Packages/main against the writer's required snapshot replacement.

Superseded files remain for 30 days after leaving the active index. Cleanup runs on the affected feed during publication, not on an independent schedule. Files in an idle feed can therefore remain longer. `retention.json` records retirement and `build.json` records the files currently referenced by signed indexes.

## Workflow entry points

| Workflow | Responsibility |
| --- | --- |
| [SNode.C build-distribution-packages.yml](https://github.com/SNodeC/snode.c/blob/master/.github/workflows/build-distribution-packages.yml) | Notify exact version-tag identity; execute coordinator target builds and report unsigned artifacts |
| [MQTTSuite build-distribution-packages.yml](https://github.com/SNodeC/mqttsuite/blob/master/.github/workflows/build-distribution-packages.yml) | Same lifecycle, using the corresponding published SNode.C dependency |
| [sign-and-publish-packages.yml](https://github.com/SNodeC/DistributionPackages/blob/main/.github/workflows/sign-and-publish-packages.yml) | Verify artifact identity/bytes, sign and publish; completion wakes dependent admission |

The manual-only **Publish package guides and render status** workflow in DistributionPackages runs the default-branch renderer against the current Packages state, with the existing publication concurrency group and metadata retry transaction. It does not build, sign or publish packages, and is not triggered automatically after merge. Run it only after explicit approval. Locally: `python3 -m ci.publish.publication render /path/to/Packages`. The local renderer preserves authored documentation, feed records and `status.json`. The approved manual workflow also hands off the current `site/` README, documentation and keys guide through the same metadata retry transaction; it removes obsolete documentation without changing key bytes or installer behavior.

Operator retries and expired-capture recovery follow the [recovery runbook](ci-orchestration.md#state-and-recovery). Source workflows accept coordinator requests rather than arbitrary manual tag inputs. A new capture requires an authorized source tag notification.

There are no workflows in Packages. Shared platform scripts have one implementation in DistributionPackages; the source repositories own and execute the build jobs. Signing and publication tools remain checked out from DistributionPackages’ own Git history at the captured packaging commit, never supplied by an uploaded artifact. The presentation-only exception is an isolated, read-only navigation worker from `SNodeC/.github@main`, with PyYAML; it receives no feed paths, CI credentials or signing environment. Signing secrets exist only in DistributionPackages. OpenWrt index signing and RPM package/index signing happen there after upload; APT metadata is also signed there. Builds need no private signing key.

OpenWrt signer executables (`usign` and `apk`) are stored in this repository’s GitHub Actions cache, not in Git or Packages. The exact key includes runner OS/architecture, runner-image version and the SHA-256 content hash of the capture-pinned `ci/publish/tools.sh`; pinned source revisions and build options are inside that script. There are no fallback keys. A miss, eviction or missing executable rebuilds both tools from the audited pinned sources; a hit installs the cached executables without cloning or compiling them. Only executables are cached, never private keys, tokens or package artifacts. Existing captures keep their original script; new captures after this change use the cache. Publication still verifies signatures before committing feeds.

The coordinator App needs Actions read/write for workflow dispatch/artifacts and Contents read/write for capture/status/publication and Actions read for cross-repository artifacts. Reader tokens grant Contents read; capture/publication readers use Actions read. Control dispatch authority covers sources and DP only. Separate Contents-write tokens are scoped to Packages for status and feed writes. The coordinator key itself retains installation-wide authority; source notify Actions-write retains cancellation/artifact-deletion capabilities. See [CI setup and activation](setup.md#banner).

After handing off the moved documentation paths to Packages, do not rerun an old capture without a separately approved migration: its capture-pinned renderer does not acquire this correction. A new package capture must use the merged DistributionPackages correction.

A release capture remains the generation identity across repositories. Uploaded artifact names include the source build attempt. A publisher retry reuses that attempt, not its own workflow attempt; a source build retry reports its new attempt. A dependent application has attempt zero while waiting for its library; its first actual build starts attempt one, independently of any SNode.C retries. Already-published unsigned content is recognized before signing again. Retrying a dispatch uses an existing matching upstream workflow run instead of deliberately starting another build. To retry compilation, use Re-run failed jobs in the source repository; to retry signing or pushing, rerun the failed publication in DistributionPackages.

Publication wakes the bounded coordinator; it dispatches newly ready transitive dependents against the exact published Packages commit. Lost callbacks and uncertain dispatches are recovered from GitHub state on later wakes. Publication receipts prevent duplicate writes.

Shared Python downloads in `ci.repository.fetch` make at most four attempts for recognized transient transport failures, with fallback delays of 1, 5 and 15 minutes. HTTP 429 and 503 responses can supply `Retry-After` as seconds or an HTTP date; valid values are bounded to 0–30 minutes, and missing or malformed values retain the fallback delay. Downloads stream into private temporary storage, which is removed before retrying; a destination is replaced only after a complete transfer. Certificate, authentication, missing-file, unclassified transport and local filesystem errors fail closed. Checksum and captured-source validation remain outside the retry loop. The same transport serves retained dependency packages, OpenWrt SDK metadata and archives, and MQTTSuite's captured-publication baseline. A running package generation keeps its captured implementation; merging this change affects new captures, not existing builds or reruns of an old capture.

## Revision numbering

SNode.C and MQTTSuite have independent package revision counters. A SNode.C release reserves the next number for both projects; an MQTTSuite-only release advances only MQTTSuite. Numbers are shared across targets of the same project.

`Packages/status.json` holds the authoritative integer counters at `counters["snode.c"]` and `counters["mqttsuite"]`. Source preparation increments each selected counter once and saves its run allocation with a Git lease. Competing metadata or feed commits cause a fresh read and retry; allocation failure stops preparation before any build can use an unreserved number. Retries reuse that allocation without incrementing; cancelled runs leave gaps. History and feed versions never determine the next number. With both counters at zero, the next SNode.C release allocates r1 for both projects. Reset counters only while CI is stopped and preparing a fresh feed; existing feeds retain protection against older publications. Source versions still come from upstream version tags.

## Coverage and tests

Each source repository owns its authoritative `ci/packages.json` matrix. DP contains no duplicate release/architecture inventory. Current source definitions retain 76 targets for the framework and MQTTSuite, and 26 native/Pi targets for IDP. Presentation ordering is separate from admission priority.

The inherited build scripts run SNode.C's upstream CTests, including through QEMU for OpenWrt. They build and package MQTTSuite but do not currently invoke an MQTTSuite CTest suite. This migration does not claim equivalent test coverage or change upstream production code to introduce it.

## Source records and documentation

Each feed's `build.json` records versions, source tags and commits, checksums and publication context. APT aggregates architectures within a suite. These records provide provenance; package and index signatures establish signing authenticity.

[publication.py](https://github.com/SNodeC/DistributionPackages/blob/HEAD/ci/publish/publication.py) copies current authored public documentation from `site/` and the capture-pinned `install/` into Packages on publication. Its single renderer generates per-project pages under `status/`, the `status/README.md` entry page and its shared generated section list. The overview shows Latest release, derived from the newest captured source tag and allocated revision for each project. Project tables show Architecture, Available, Published (UTC), In build and Links. Available comes from feed records; In build describes only that latest revision. Build log selects its build job or the job that produced Available; Packages opens the feed directory. Project publication times appear only when attributable to that project and revision; unrecorded values render as `—`.

Capture initializes per-target nodes. Completion callbacks carry real source job and artifact identities; DP verifies them through GitHub before publishing. Bounded reconciliation recovers lost callbacks and closes failed/skipped/unsatisfiable nodes. Receipts restore published facts after lost status updates. Separate source and publication budgets allow operator retry. Rendering is outside signed-feed acceptance; presentation never authorizes execution. See the [recovery runbook](ci-orchestration.md#state-and-recovery).

Status circles are fixed named images under `status/badges/`; the generated table changes which image it references. This avoids stale per-target image contents, but GitHub may still cache the Markdown page. GitHub scheduling and network failures can delay updates; force-cancellation or runner loss can prevent final steps from executing. A bounded scheduled reconciliation supplements callbacks; no permanent polling loop is used.

Guides and package catalogs are handwritten. Keep their architecture tables in agreement with the repository-owned definitions. Native component names follow upstream CPack; `snodec-control` contains the configuration tool.

## Signing-key verification

The installer obtains these public keys from Packages/main. Compare both checkouts:

```sh
for key in keys/*.asc keys/*.pub keys/*.pem; do
  cmp "$key" "../Packages/keys/${key##*/}" || exit 1
done
```

Compute the fingerprints shown in the public keys guide:

```sh
usign -F -p keys/snodec-opkg.pub
openssl pkey -pubin -in keys/snodec-apk.pem -outform DER | openssl dgst -sha256
gpg --batch --show-keys --with-colons keys/snodec-apt.asc |
  awk -F: '$1 == "fpr" { print $10; exit }'
```

APT and RPM use the same OpenPGP key. The APK fingerprint is SHA-256 of the DER public key. Keep existing private signing keys when migrating; do not silently replace the trust identity.

## Public documentation ownership

Edit `site/README.md`, `site/docs/` and the public key guide in `site/keys/README.md`, not the generated Packages snapshot. Publication overlays current default-branch authored documentation while executable tools and `install/` remain captured. Per-project status pages are generated under `status/`. New event timestamps are recorded in the `status.json` timeline only by captures containing the updated tooling; older events render as `—`. Register a repository in `ci/projects.json` and provide its pinned `ci/packages.json` and source build integration as described in [setup](setup.md). No central product adapter or target inventory is added. Intake, callback and artifact verification still authorize each release; presentation grants no signing authority. New job-ID handoffs and the renamed-key publication require a fresh capture containing the updated tooling. The manual render workflow also hands off the current `site/` README, guides and keys guide before regenerating status. Do not rerun an older capture as the activation procedure. Captures through r9 used `40d7a9638125de8e384150693cf3328d6afaed72` (before circle presentation and the canonical opkg copy). Capture r10 uses `d3efc7808fbd9902c6ba7e7aa4ad84049cbe7658`, which already renders circles and both key names but predates this documentation correction. Publications and source status events execute the captured renderer/template. Consequently, even r10 can regenerate its existing navigation and legend until a new capture uses the correction. Current authored guides are overlaid separately; do not change executable trust rules to update presentation.

## Product ownership and IDP packages

Registered repository names come from the DP master config; each selected commit owns its definition. `ci.repository.PROJECTS` is a derived runtime view, not a product or ownership authority. `snode.c-idp` is a native dependent of `snode.c`; its package prefix is `snodec-idp`. Longest-prefix ownership prevents IDP packages being classified as framework components. CPack supplies the component inventory.

Publication validates the originating workflow, source run/attempt/job and artifact ID/digest against the immutable capture. Admission and publication separately validate transitive prerequisite readiness and identity/checksums. A changed framework rejects stale application packages; unrelated newer sibling packages survive APT, RPM, opkg and APK publication.

The IDP build runs offline authentication and deployment-helper tests, packages the server/client development files and optional example, installs the packages in the disposable target, and compiles installed consumers plus the client-only configuration. The [IDP package catalog](../site/docs/catalogs/snodec-idp.md#banner) is authored here and published with the other guides.

Pinned ownership is the package namespace at the exact source commit recorded by the row manifest, independent of the historical build matrix. The source receives verified baseline ownership facts in the existing request payload; its reader token is not widened. Missing historical JSON blocks publication on shared rows. A-first bootstrap with new or moved tags, a separately reviewed ownership migration, and deferring cutover remain unapproved alternatives; JSON cannot be added retroactively to a commit and new VERSION numbers are not intrinsically required. Deregistration or lost read access blocks retained rows. See [setup](setup.md) for consequences and [orchestration recovery](ci-orchestration.md#state-and-recovery) for explicit operator retry of unobservable commitments. Such a retry may duplicate a queued run.

The capture workflow's rerun path has no additional triggering-actor gate in this corrective pass. A holder of notify Actions:write can rerun captures as well as cancel runs/delete artifacts. Intake's newer-request checks and immutable-capture retry rules still constrain that path. No automated rerun path was established here, so L3 is deferred and remains an explicit authorization limitation, not a claim of least privilege beyond the token's actual scope.
