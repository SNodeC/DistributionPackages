<!-- Published from DistributionPackages/site/keys; key bytes are not generated. -->
<a id="page-overview"></a>

[![Packages](../docs/media/page-banner.svg)](../README.md#project-overview)

# Package signing keys

These are public verification keys, not credentials. Keep signature verification enabled. The same key applies to every supported architecture of its package-manager family; select your distribution, release and architecture using the [installation guides](../README.md#install).

[![Install](../docs/media/menu/install.svg)](../README.md#install) [![Verify](../docs/media/menu/verify.svg)](#verify-identity) [![Troubleshoot](../docs/media/menu/troubleshoot.svg)](../docs/troubleshooting.md#page-overview)

## Apply the key

The [installer](../install/install.sh) configures the correct verification key. Manual setup also needs the signed repository configuration from your distribution guide; importing a key alone is not enough.

### OpenPGP: APT and RPM

[`snodec-apt.asc`](snodec-apt.asc) is shared by Debian, Ubuntu and Raspberry Pi OS (APT), and Rocky Linux and Fedora (DNF/RPM). APT guides download the ASCII-armored key unchanged to `/etc/apt/keyrings/snodec.asc` and reference it using `signed-by`. RPM guides install the same key as `RPM-GPG-KEY-snodec` and keep package and repository signature checks enabled.

[![Debian](../docs/media/menu/debian.svg)](../docs/debian.md#page-overview) [![Ubuntu](../docs/media/menu/ubuntu.svg)](../docs/ubuntu.md#page-overview) [![Raspberry Pi OS](../docs/media/menu/raspberrypi.svg)](../docs/raspberrypi.md#page-overview) [![Rocky Linux](../docs/media/menu/rocky.svg)](../docs/rocky.md#page-overview) [![Fedora](../docs/media/menu/fedora.svg)](../docs/fedora.md#page-overview)

### opkg: OpenWrt 24.10

[`snodec-opkg.pub`](snodec-opkg.pub) verifies opkg feed-index signatures. Import it with `opkg-key add`, then configure the matching signed feed. The old `snodec-usign.pub` URL remains a byte-identical download copy; maintainers edit only the canonical opkg key.

[![OpenWrt](../docs/media/menu/openwrt.svg)](../docs/openwrt.md#page-overview)

### APK: OpenWrt 25.12

[`snodec-apk.pem`](snodec-apk.pem) verifies APK v3 feed-index signatures. Install it in `/etc/apk/keys/`, then configure the matching APK feed. This key is for OpenWrt, not an Alpine Linux repository or Android application signing. The opkg and APK keys cannot be substituted for each other.

[![OpenWrt](../docs/media/menu/openwrt.svg)](../docs/openwrt.md#page-overview)

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
