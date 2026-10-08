# Migration to separate source and binary repositories

<p>
  <a href="maintainers.md"><img src="media/menu/back-repository-maintenance.svg" alt="← Repository maintenance" width="192" height="24"></a>
</p>

## Source and scope

The source was exported from SNodeC/OpenWRT main commit `2c5bddc6f40cfd7c92c5ea136f569c6e28a89222` into a new, independent Git repository. The original source repository and its branches remain unchanged.

The binary seed comes from SNodeC/OpenWRT packages commit `78fa4d14850adc0aa83d00fbf8a2a5f90cd77c15`. It contains every file referenced by its current 76 target inventories, their existing signed indexes, development archives and public keys. All transferred inventory files are checked against the recorded SHA-256 digests. No package is rebuilt or resigned during migration.

Previously retired packages are not copied: no client has cached an index from the new repository yet. The original feed, including those retired packages, remains available at its original URLs. Existing devices are not redirected. Newly superseded packages in Packages are retained by the normal 30-day policy.

## Repository ownership

- DistributionPackages/main owns recipes, workflows, the installer and docs.
- Packages/main owns generated feeds and status. Actions is disabled there.
- No old branches, device deployment scripts or credentials are imported.
- Upstream source repositories, release workflows and version tags are untouched.

## Revision continuity

The original migration used a revision floor of 122 to preserve package ordering. That migration floor has been removed. Allocation now increments the two explicit [independent project counters](maintainers.md#revision-numbering) in `Packages/status.json`. A fresh feed starts with both counters at zero.

## Activation boundary

The new URLs can serve the copied signed packages after publication. Automated future releases require the signing secrets, publishing GitHub App credentials and upstream notification changes described in [CI setup](setup.md).

No upstream notification changes or tag movement are included in this migration. No GitHub build is automatically triggered by the initial source push. The old publication pipeline remains separate and operational until its owner switches the upstream notification destination.

## Validation

Run the packaging boundary checks from this repository:

```sh
python3 -m unittest discover -s tests -v
python3 -m ci.publish.publication matrix
```

These tests cover release/URL selection, matrix coverage, downgrade rejection, publication ordering by generation, and one-commit publication with lease protection. They do not replace upstream application tests or a signed end-to-end CI run with configured credentials.

The OpenWrt recipes, their feature configuration and public signing keys are preserved byte-for-byte. All distribution guides point to the new installer and binary repository. The historical plan is retained only as a historical record.
