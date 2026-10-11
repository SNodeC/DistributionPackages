<!-- Published from DistributionPackages/site; edit that source, not this snapshot. -->
<a id="page-overview"></a>

[![Packages](media/page-banner.svg)](../README.md#project-overview)

# Rocky Linux

<p>
<a href="#requirements"><img src="media/menu/requirements.svg" alt="Requirements"></a>
<a href="#quick-install"><img src="media/menu/install.svg" alt="Install"></a>
<a href="#manual-repository-setup"><img src="media/menu/manual.svg" alt="Manual setup"></a>
<a href="#updates"><img src="media/menu/updates.svg" alt="Updates"></a>
<a href="../status/README.md#page-overview"><img src="media/menu/status.svg" alt="Status"></a>
<a href="#troubleshooting"><img src="media/menu/troubleshoot.svg" alt="Troubleshoot"></a>
</p>

## Requirements

Supported releases: `9`, `10`. Match the release and package architecture installed on your device. Keep official repositories enabled for dependencies.

Use an account with `sudo`, or run administrative commands directly as root. Install `curl` and CA certificates before downloading the installer.

```sh
. /etc/os-release
printf 'Distribution: %s\nRelease: %s\n' "$ID" "$VERSION_ID"
rpm --eval '%{_arch}'
```

```sh
sudo dnf install ca-certificates curl
```

Rocky Linux 10 requires x86-64-v3 on x86 systems. ARM64 packages use `aarch64`. Enable CRB and EPEL before either installation method:

```sh
sudo dnf install -y dnf-plugins-core epel-release
sudo dnf config-manager --set-enabled crb
```

## Quick install

```sh
curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/install/install.sh \
  -o /tmp/snodec-install-feed.sh &&
sudo sh /tmp/snodec-install-feed.sh
```

The installer detects the distribution, release and package architecture, checks that an index exists, installs the signing key, configures the repository and installs the complete package set. Configure applications before starting them. Prefer manual setup? Use [Manual repository setup](#manual-repository-setup).

## Choose packages

See the [SNode.C catalog](snodec-package-options.md#page-overview) and [MQTTSuite catalog](mqttsuite-package-options.md#page-overview) for package roles and after-install configuration.

Prepare the repository without installing packages:

```sh
curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/install/install.sh \
  -o /tmp/snodec-install-feed.sh &&
sudo sh /tmp/snodec-install-feed.sh --prepare
```

For only the broker and command-line client:

```sh
sudo dnf install mqttsuite-broker mqttsuite-cli
```

Dependencies are installed automatically. For the full selection after manual preparation, install the complete-project packages in the project catalogs.

```sh
sudo dnf install snodec mqttsuite
```

## Updates

```sh
sudo dnf upgrade 'snodec*' 'mqttsuite*'
```

For selective installations, name the installed components rather than adding the complete metapackages. After a distribution upgrade, configure the repository for its new supported release and refresh metadata.

## Manual repository setup

These commands configure the signed repository without installing SNode.C or MQTTSuite.

APT and RPM repositories use the same signing key. Its download filename is `snodec-apt.asc`; the commands below install it under the RPM-specific name `RPM-GPG-KEY-snodec`.

```sh
sudo install -d -m 755 /etc/pki/rpm-gpg
sudo curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/keys/snodec-apt.asc \
  -o /etc/pki/rpm-gpg/RPM-GPG-KEY-snodec
sudo rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-snodec
sudo tee /etc/yum.repos.d/snodec.repo >/dev/null <<'REPO'
[snodec]
name=SNode.C and MQTTSuite
baseurl=https://raw.githubusercontent.com/SNodeC/Packages/main/rocky/$releasever/$basearch/
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-snodec
REPO
sudo dnf makecache
```

The quoted `REPO` delimiter preserves `$releasever` and `$basearch`; DNF expands them for the installed system. Both RPM packages and repository metadata are signature-checked.

Then [choose packages](#choose-packages) to install.

## Source records

See [per-project availability and source records](../status/README.md#page-overview) for every release and architecture.

## Troubleshooting

See [common problems and fixes](troubleshooting.md#page-overview) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Dependencies are missing | Enable CRB and EPEL as shown in Requirements. |
| Illegal instruction on x86 | Check the x86-64-v3 requirement for Rocky Linux 10. |
