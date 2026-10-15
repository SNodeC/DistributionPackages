<!-- Published from DistributionPackages/site/keys; key bytes are not generated. -->

<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../docs/media/nav/banner-signing-keys-compact.svg"><img src="../docs/media/nav/banner-signing-keys.svg" alt="Packages — Signing keys" width="100%"></picture></p>
<p><a href="../README.md#banner" title="Up to Packages"><picture><source media="(prefers-color-scheme: dark)" srcset="../docs/media/nav/up-packages-dark.svg"><img src="../docs/media/nav/up-packages-light.svg" alt="Up to Packages" title="Up to Packages" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../docs/media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="../docs/media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../docs/media/nav/account-dark.svg"><img align="right" src="../docs/media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../docs/media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../docs/media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../docs/media/nav/organization-dark.svg"><img align="right" src="../docs/media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../README.md#banner" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../docs/media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../docs/media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../docs/media/nav/repository-dark.svg"><img align="right" src="../docs/media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# Package signing keys

<!-- snodec:begin menu -->
[![Install](../docs/media/menu/install.svg)](../README.md#install) [![Verify](../docs/media/menu/verify.svg)](#verify-identity) [![Troubleshoot](../docs/media/menu/troubleshoot.svg)](../docs/troubleshooting.md#banner)
<!-- snodec:end menu -->

These are public verification keys, not credentials. Keep signature verification enabled. The same key applies to every supported architecture of its package-manager family; select your distribution, release and architecture using the [installation guides](../README.md#install).

## Apply the key

The [installer](../install/install.sh) configures the correct verification key. Manual setup also needs the signed repository configuration from your distribution guide; importing a key alone is not enough.

### OpenPGP: APT and RPM

[`snodec-apt.asc`](snodec-apt.asc) is shared by Debian, Ubuntu and Raspberry Pi OS (APT), and Rocky Linux and Fedora (DNF/RPM). APT guides download the ASCII-armored key unchanged to `/etc/apt/keyrings/snodec.asc` and reference it using `signed-by`. RPM guides install the same key as `RPM-GPG-KEY-snodec` and keep package and repository signature checks enabled.

Next: [Debian](../docs/installation/debian.md#banner), [Ubuntu](../docs/installation/ubuntu.md#banner), [Raspberry Pi OS](../docs/installation/raspberry-pi-os.md#banner), [Rocky Linux](../docs/installation/rocky-linux.md#banner), [Fedora](../docs/installation/fedora.md#banner).

### opkg: OpenWrt 24.10

[`snodec-opkg.pub`](snodec-opkg.pub) verifies opkg feed-index signatures. Import it with `opkg-key add`, then configure the matching signed feed. opkg is the package manager; usign is the feed-signing tool/format. `snodec-opkg.pub` is the canonical filename; [`snodec-usign.pub`](snodec-usign.pub) is the byte-identical former name, preserved for older instructions.

Next: [OpenWrt](../docs/installation/openwrt.md#banner).

### APK: OpenWrt 25.12

[`snodec-apk.pem`](snodec-apk.pem) verifies APK v3 feed-index signatures. Install it in `/etc/apk/keys/`, then configure the matching APK feed. This key is for OpenWrt, not an Alpine Linux repository or Android application signing. The opkg and APK keys cannot be substituted for each other.

Next: [OpenWrt](../docs/installation/openwrt.md#banner).

Keys are architecture-independent; feed URLs and package compatibility are not. Never choose an architecture by downloading a different key.

## Verify identity

Compare a key’s computed fingerprint with the table below to detect a mismatch. This table is independent authenticity evidence only if you obtained it through a separate trusted channel. Downloading both the key and this table from this repository does not establish such a channel; none is prescribed here.

| Key | Fingerprint |
| --- | --- |
| OpenPGP primary key | `8BBFD49E3C826FDB1416C79E60046744B15B0E05` |
| opkg (usign) key ID | `f6fd78dca70698e8` |
| APK public key, SHA-256 of DER | `293fb661ae75b821a15fa14f1399cd432d2f444bec138ba0e9ac397c81dbe645` |

### Downloaded keys

From a local checkout (or a download saved at these same paths), use `gpg`, `usign` and `openssl` as applicable:

```sh
gpg --batch --show-keys --with-colons keys/snodec-apt.asc |
  awk -F: '$1 == "fpr" { print $10; exit }'
usign -F -p keys/snodec-opkg.pub
openssl pkey -pubin -in keys/snodec-apk.pem -outform DER | openssl dgst -sha256
```

### Installed keys

Use the command for your package manager, then compare the result with the single fingerprint table above. These inspect the installed key file; they do not prove that its repository configuration is correct. The inspection tools must be available (`gpg` for OpenPGP, `usign` on opkg-based OpenWrt, `openssl` for APK). If absent on a device, inspect a copy on a trusted computer rather than bypassing verification.

```sh
# APT: installed ASCII-armored key
gpg --batch --show-keys --with-colons /etc/apt/keyrings/snodec.asc |
  awk -F: '$1 == "fpr" { print $10; exit }'
# RPM: installed public-key file
gpg --batch --show-keys --with-colons /etc/pki/rpm-gpg/RPM-GPG-KEY-snodec |
  awk -F: '$1 == "fpr" { print $10; exit }'
```

On OpenWrt 24.10, `opkg-key add` stores the key under its usign key ID. To avoid copying that ID into another authority, list the installed keys:

```sh
for key in /etc/opkg/keys/*; do
  [ -f "$key" ] || continue
  printf '%s: ' "$key"
  usign -F -p "$key"
done
```

On OpenWrt 25.12:

```sh
openssl pkey -pubin -in /etc/apk/keys/snodec-apk.pem -outform DER |
  openssl dgst -sha256
```

[Installation troubleshooting](../docs/troubleshooting.md#banner) covers missing keys, rejected signatures and dependency errors. Do not bypass a signature error with an untrusted-install option.
