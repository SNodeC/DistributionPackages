<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="banner"></a><a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../media/nav/banner-installation-compact.svg"><img src="../media/nav/banner-installation.svg" alt="Packages — Installation" width="100%"></picture></p>
<p><a href="README.md#banner" title="Up to Installation"><picture><source media="(prefers-color-scheme: dark)" srcset="../media/nav/up-installation-dark.svg"><img src="../media/nav/up-installation-light.svg" alt="Up to Installation" title="Up to Installation" width="160" height="28"></picture></a><a href="https://github.com/VolkerChristian#banner" title="Volker Christian account"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/account-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/account-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/account-dark.svg"><img align="right" src="../media/nav/account-light.svg" alt="Volker Christian account" title="Volker Christian account"></picture></a><a href="https://github.com/SNodeC#banner" title="SNode.C organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/organization-dark.svg"><img align="right" src="../media/nav/organization-light.svg" alt="SNode.C organization" title="SNode.C organization"></picture></a><a href="../../README.md#banner" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/repository-dark.svg"><img align="right" src="../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# Fedora: signed repository setup

This page configures the package source only. Choose your project in the [Fedora installation overview](../installation/fedora.md#banner).

## Requirements

Supported releases: `43`, `44`. Match the release and package architecture installed on your device. Keep official repositories enabled for dependencies.

Use an account with `sudo`, or run administrative commands directly as root. Install `curl` and CA certificates before downloading the installer.

```sh
. /etc/os-release
printf 'Distribution: %s\nRelease: %s\n' "$ID" "$VERSION_ID"
rpm --eval '%{_arch}'
```

```sh
sudo dnf install ca-certificates curl
```

## Configure the repository


These commands configure the signed repository without installing application packages.

APT and RPM repositories use the same signing key. Its download filename is `snodec-apt.asc`; the commands below install it under the RPM-specific name `RPM-GPG-KEY-snodec`.

```sh
(
  set -eu
  . /etc/os-release
  [ "$ID" = fedora ] || { echo "Requires fedora"; exit 1; }
  suite=${VERSION_ID%%.*}
  case "$suite" in
    43|44) ;;
    *) echo "Unsupported release"; exit 1 ;;
  esac
  arch=$(rpm --eval '%{_arch}')
  case "$arch" in
    x86_64|aarch64) ;;
    *) echo "Unsupported architecture"; exit 1 ;;
  esac
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  curl -fsSL "$base/fedora/$suite/$arch/repodata/repomd.xml" -o "$tmp/index"
  curl -fsSL "$base/keys/snodec-apt.asc" -o "$tmp/key"
  sudo install -d -m 755 /etc/pki/rpm-gpg /etc/yum.repos.d
  sudo install -m 644 "$tmp/key" /etc/pki/rpm-gpg/RPM-GPG-KEY-snodec
  sudo rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-snodec
  sudo tee /etc/yum.repos.d/snodec.repo >/dev/null <<REPO
[snodec]
name=SNode.C Packages
baseurl=$base/fedora/\$releasever/\$basearch/
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-snodec
REPO
  sudo dnf makecache
)
```

The escaped `$releasever` and `$basearch` remain literal in the file; DNF expands them for the installed system. Both RPM packages and repository metadata are signature-checked.

Verify the [installed signing key](../../keys/README.md#installed-keys) before installing packages.

The repository is ready. Return to the [project choices](../installation/fedora.md#banner) to install the packages you need.

## Source records

In [source records](../../fedora/), `<release>/<architecture>/build.json` belongs to the feed. **Packages** opens its `Packages/` subdirectory, not the record itself.

`build.json` records source tags and commits, package versions, checksums and publication context. On the [project status pages](../../status/README.md#banner), **Build log** opens the recorded build job or release run. See [column semantics](../publication.md#latest-release-available-and-in-build) for missing historical records.

Native package definitions: [SNode.C CPack](https://github.com/SNodeC/snode.c/blob/HEAD/cmake/Packing.cmake) and [MQTTSuite CPack](https://github.com/SNodeC/mqttsuite/blob/HEAD/cmake/Packing.cmake).

## Troubleshooting

See [common problems and fixes](../troubleshooting.md#banner) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| DNF selects the wrong release | Check `VERSION_ID` and DNF’s `$releasever`; do not mix Fedora release repositories. |
