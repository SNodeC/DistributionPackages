<!-- Published from DistributionPackages/site/keys; key bytes are not generated. -->
<a id="page-overview"></a>

[![Packages](../docs/media/page-banner.svg)](../README.md#project-overview)

# Package signing keys

These are public verification keys, not credentials. Keep signature verification enabled. The same key applies to every supported architecture of its package-manager family; select your distribution, release and architecture using the [installation guides](../README.md#install).

| Key | Distributions and package manager | Installation |
| --- | --- | --- |
| [snodec-apt.asc](snodec-apt.asc) | Debian, Ubuntu and Raspberry Pi OS (APT); Rocky Linux and Fedora (DNF/RPM) | [Debian](../docs/debian.md#page-overview) · [Ubuntu](../docs/ubuntu.md#page-overview) · [Raspberry Pi OS](../docs/raspberrypi.md#page-overview) · [Rocky Linux](../docs/rocky.md#page-overview) · [Fedora](../docs/fedora.md#page-overview) |
| [snodec-opkg.pub](snodec-opkg.pub) | OpenWrt 24.10, opkg package-feed index signatures | [OpenWrt](../docs/openwrt.md#page-overview) |
| [snodec-apk.pem](snodec-apk.pem) | OpenWrt 25.12, APK v3 package-feed index signatures | [OpenWrt](../docs/openwrt.md#page-overview) |

APT and RPM share the same OpenPGP key despite its APT-labelled download filename. The old `snodec-usign.pub` download URL remains available in Packages as a generated, byte-identical copy of `snodec-opkg.pub`; maintainers edit only the canonical key. The OpenWrt keys are different formats and cannot be substituted for one another. The APK key here is for OpenWrt, not an Alpine Linux package repository or Android application signing.

## Apply the key

The [installer](../install/install.sh) configures the correct key for its detected package manager. For manual setup, use the complete commands in your distribution guide: importing a key alone does not configure a repository.

- **APT:** dearmor `snodec-apt.asc` into the keyring used by the guide's `signed-by` repository configuration. Do not enable trust for unrelated repositories.
- **DNF/RPM:** download the same OpenPGP key as `RPM-GPG-KEY-snodec`; the guide's repository configuration references it using `gpgkey` and keeps signature checks enabled.
- **OpenWrt / opkg:** import the public usign key with `opkg-key add`, then configure the matching signed feed.
- **OpenWrt / APK:** install `snodec-apk.pem` in `/etc/apk/keys/`, then configure the matching APK feed.

Keys are architecture-independent; feed URLs and package compatibility are not. Never choose an architecture by downloading a different key.

## Verify identity

Compare these fingerprints against a separately trusted copy before accepting a replacement key. A fingerprint fetched from the same location as a key is not independent proof of authenticity.

| Key | Fingerprint |
| --- | --- |
| OpenPGP primary key | `8BBFD49E3C826FDB1416C79E60046744B15B0E05` |
| usign key identifier | `f6fd78dca70698e8` |
| APK public key, SHA-256 of DER | `293fb661ae75b821a15fa14f1399cd432d2f444bec138ba0e9ac397c81dbe645` |

From a local checkout:

```sh
gpg --batch --show-keys --with-colons keys/snodec-apt.asc |
  awk -F: '$1 == "fpr" { print $10; exit }'
usign -F -p keys/snodec-opkg.pub
openssl pkey -pubin -in keys/snodec-apk.pem -outform DER | openssl dgst -sha256
```

[Installation troubleshooting](../docs/troubleshooting.md#page-overview) covers missing keys, rejected signatures and dependency errors. Do not bypass a signature error with an untrusted-install option.
