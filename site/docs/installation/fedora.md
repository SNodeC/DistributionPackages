<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->

<!-- snodec:begin page-header -->
<a id="page-overview"></a>
<p><picture><source media="(max-width: 640px)" srcset="../media/nav/banner-installation-compact.svg"><img src="../media/nav/banner-installation.svg" alt="Packages — Installation" width="100%"></picture></p>
<p><a href="README.md#page-overview" title="Up to Installation"><picture><source media="(prefers-color-scheme: dark)" srcset="../media/nav/up-installation-dark.svg"><img src="../media/nav/up-installation-light.svg" alt="Up to Installation" title="Up to Installation" width="160" height="28"></picture></a><a href="https://github.com/SNodeC" title="SNodeC organization"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/organization-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/organization-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/organization-dark.svg"><img align="right" src="../media/nav/organization-light.svg" alt="SNodeC organization" title="SNodeC organization"></picture></a><a href="../../README.md#project-overview" title="Packages repository"><picture><source media="(max-width: 640px) and (prefers-color-scheme: dark)" srcset="../media/nav/repository-icon-dark.svg"><source media="(max-width: 640px)" srcset="../media/nav/repository-icon-light.svg"><source media="(prefers-color-scheme: dark)" srcset="../media/nav/repository-dark.svg"><img align="right" src="../media/nav/repository-light.svg" alt="Packages repository" title="Packages repository"></picture></a><br clear="all"></p>
<!-- snodec:end page-header -->

# Fedora

<!-- snodec:begin menu -->
<p>
<a href="#requirements"><img src="../media/menu/requirements.svg" alt="Requirements"></a>
<a href="#quick-install"><img src="../media/menu/menu-quick-install.svg" alt="Quick install"></a>
<a href="#choose-packages"><img src="../media/menu/menu-custom-install.svg" alt="Custom install"></a>
<a href="#manual-repository-setup"><img src="../media/menu/manual.svg" alt="Manual setup"></a>
<a href="#updates"><img src="../media/menu/updates.svg" alt="Updates"></a>
<a href="../../status/README.md#page-overview"><img src="../media/menu/status.svg" alt="Status"></a>
<a href="#troubleshooting"><img src="../media/menu/troubleshoot.svg" alt="Troubleshoot"></a>
</p>
<!-- snodec:end menu -->

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

## Quick install

Install the complete package sets:

```sh
(
  set -eu
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  curl -fsSL "$base/install/install.sh" -o "$tmp/install.sh"
  sudo sh "$tmp/install.sh"
)
```

The installer detects the distribution, release and package architecture, checks that an index exists, installs the signing key, configures the repository and installs the complete package set. Configure applications before starting them. For manual configuration, use [Manual repository setup](#manual-repository-setup).

**Check**

```sh
rpm -q snodec mqttsuite
```

Both requested packages show their installed version, release and architecture; no “not installed” message appears. Next: [SNode.C configuration](../catalogs/snodec.md#after-installation) or [MQTTSuite configuration and deployment](../catalogs/mqttsuite.md#after-installation).

<a id="choose-packages"></a>

## Custom install

Prepare the repository without installing packages, then install only what you need:

```sh
(
  set -eu
  tmp=$(mktemp -d /tmp/snodec.XXXXXX)
  trap 'rm -rf "$tmp"' EXIT HUP INT TERM
  base=https://raw.githubusercontent.com/SNodeC/Packages/main
  curl -fsSL "$base/install/install.sh" -o "$tmp/install.sh"
  sudo sh "$tmp/install.sh" --prepare
)
```

For only the broker and command-line client:

<a id="install-selected-components"></a>

```sh
sudo dnf install mqttsuite-broker mqttsuite-cli
```

Dependencies are installed automatically.

**Check**

```sh
rpm -q mqttsuite-broker mqttsuite-cli
```

Both requested packages show their installed version, release and architecture; no “not installed” message appears. Next: [SNode.C configuration](../catalogs/snodec.md#after-installation) or [MQTTSuite configuration and deployment](../catalogs/mqttsuite.md#after-installation).

See the [SNode.C catalog](../catalogs/snodec.md#page-overview) and [MQTTSuite catalog](../catalogs/mqttsuite.md#page-overview) for package roles and after-install configuration.

## Manual repository setup

These commands configure the signed repository without installing SNode.C or MQTTSuite.

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
name=SNode.C and MQTTSuite
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

Install the complete sets after manual setup:

```sh
sudo dnf install snodec mqttsuite
```

**Check**

```sh
rpm -q snodec mqttsuite
```

Both requested packages show their installed version, release and architecture; no “not installed” message appears. Next: [SNode.C configuration](../catalogs/snodec.md#after-installation) or [MQTTSuite configuration and deployment](../catalogs/mqttsuite.md#after-installation).

The repository is ready; [install only the selected components](#install-selected-components) you need.

## Updates

```sh
sudo dnf upgrade 'snodec*' 'mqttsuite*'
```

The quoted patterns upgrade installed matching packages and their dependencies; they do not select the complete metapackages for installation. DNF substitutes the new `$releasever` after a distribution upgrade. Confirm that the new release is supported and refresh metadata with `sudo dnf makecache --refresh`. Installer-created repository URLs are fixed to the detected release; rerun the installer for a supported new release in that case.

## Source records

In [source records](../../fedora/), `<release>/<architecture>/build.json` belongs to the feed. **Packages** opens its `Packages/` subdirectory, not the record itself.

`build.json` records source tags and commits, package versions, checksums and publication context. On the [project status pages](../../status/README.md#page-overview), **Build log** opens the recorded build job or release run. See [column semantics](../publication.md#latest-release-available-and-in-build) for missing historical records.

Native package definitions: [SNode.C CPack](https://github.com/SNodeC/snode.c/blob/HEAD/cmake/Packing.cmake) and [MQTTSuite CPack](https://github.com/SNodeC/mqttsuite/blob/HEAD/cmake/Packing.cmake).

## Troubleshooting

See [common problems and fixes](../troubleshooting.md#page-overview) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| DNF selects the wrong release | Check `VERSION_ID` and DNF’s `$releasever`; do not mix Fedora release repositories. |
