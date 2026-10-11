# Package-page correction verification

Source snapshot: `SNodeC/Packages` at `db26363d86b9bbdb649bad3ecf9ed13d7706d61a`. The snapshot is regenerated from DistributionPackages' authored `site/`, existing installer/public keys, and single status renderer. Package binaries, signed indexes, feed manifests, retention and `status.json` are not regenerated.

## Restored invariants

- A coherent snapshot deploys the authored hub, guides, key guide and generated status together; a source merge alone is not a deployment.
- Overview tables contain Project / Latest release / Status, with no availability counts.
- Both project pages have 76 compact rows and exactly Architecture / Available / Published (UTC) / In build / Links. Status indicators are 14 px filled circles with a legend, alt text and hover descriptions.
- Page banners are 1280×80, one quarter of the main banner's 1280×320 aspect ratio. Menus use rendered SVG buttons, 16 px semibold labels; further/route buttons use the existing bold 9×4 SVG arrow, centered at y=14. Native GitHub wrapping remains untouched.
- Every distribution guide follows Requirements / Choose packages / Quick install / Manual repository setup / Updates / Source records / Troubleshooting. Choice precedes installation; menus match that order.
- Catalog navigation uses buttons; queries cover APT, RPM, opkg and APK. MQTTSuite deployment links directly to its deployment guide.
- Fingerprints have one authored home, the key guide. Its APT instructions match the guides' ASCII-armored `.asc` setup. All existing key bytes and the legacy usign URL are preserved; `snodec-opkg.pub` is a byte-identical canonical download.
- Optional catalog navigation appears only for a catalog actually present in the published documentation. Metadata sparse checkouts include docs so that this is also true during status events. Adding a third PROJECTS entry needs no placeholder catalog or template edit.

## Checks

- 63 unit/integration tests passed, no skips, including disposable-key signing/publication, concurrent writers, registry extension, guide/menu order, typography, banner aspect ratio and documentation consistency.
- All 67 checked-out JSON records, including status/retention/feed records, have unchanged SHA-256 hashes. All three original public key files are byte-identical; the new opkg filename matches the old usign key.
- Protected feed paths are excluded from the Packages diff; no workflow definitions, signing/provenance code, run names, triggers, concurrency, licences, branches or tags changed.
- Native GitHub browser review covers all 21 PR Markdown pages plus the keys directory: zero broken images; actual overview width 838px, child width 1012px; both project pages have 76 five-column rows at 38.39px height, with circle centers within 0.02px of version text. The internal-link audit covers 626 destinations; two catalog Use anchors found by it were corrected and 22 focused page tests passed afterward. An earlier full run hit a concurrent-clone fixture race; its unchanged repeat passed all 63 tests. Live pages are checked after merge. No CI dispatch or package build is needed or authorized for this cutover.

## Activation boundary

The owner explicitly authorizes source and generated-snapshot PRs and their merge without CI. Old captures still freeze their older executable tooling; do not rerun an old capture to activate this design. New job-level build-log records require a future explicitly requested fresh capture. Historic run-level links and unrecorded timestamps are not fabricated.
