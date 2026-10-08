# Fedora

<p>
  <a href="../README.md#distributions"><img src="media/menu/back-all-distributions.svg" alt="← All distributions" width="140" height="24"></a>
</p>

<p align="center">
  <a href="#requirements" title="Requirements"><img src="media/menu/requirements-102.svg" alt="Requirements" width="102" height="24"></a>
  <a href="#quick-install" title="Quick install"><img src="media/menu/install-102.svg" alt="Quick install" width="102" height="24"></a>
  <a href="#choose-packages" title="Choose packages"><img src="media/menu/packages-102.svg" alt="Choose packages" width="102" height="24"></a>
  <a href="#configure-and-run" title="Configure and run"><img src="media/menu/configure-102.svg" alt="Configure and run" width="102" height="24"></a>
  <a href="#updates" title="Updates"><img src="media/menu/updates-102.svg" alt="Updates" width="102" height="24"></a>
  <a href="#manual-repository-setup" title="Manual repository setup"><img src="media/menu/manual-setup-102.svg" alt="Manual repository setup" width="102" height="24"></a>
  <a href="#reference" title="Reference"><img src="media/menu/reference-102.svg" alt="Reference" width="102" height="24"></a>
  <a href="#troubleshooting" title="Troubleshooting"><img src="media/menu/help-102.svg" alt="Troubleshooting" width="102" height="24"></a>
</p>

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

```sh
curl -fsSL https://raw.githubusercontent.com/SNodeC/Packages/main/install/install.sh \
  -o /tmp/snodec-install-feed.sh &&
sudo sh /tmp/snodec-install-feed.sh
```

The installer detects the distribution, release and package architecture, checks that an index exists, installs the signing key, configures the repository and installs the complete package set. Configure applications before starting them. Prefer manual setup? Use [Manual repository setup](#manual-repository-setup).

## Choose packages

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

Dependencies are installed automatically. For the full selection after manual preparation, install the complete-project packages listed below.

| Package | Contents |
| --- | --- |
| `snodec` | All framework components, headers, examples and configuration tool |
| `snodec-apps` | Demonstration applications |
| `snodec-control` | Component containing `snodec-control` |
| `mqttsuite` | All five applications and both mapping plugins |
| `mqttsuite-broker` | MQTT broker |
| `mqttsuite-cli` | Publish/subscribe command-line client |

See the complete [SNode.C](snodec-package-options.md) and [MQTTSuite](mqttsuite-package-options.md) package catalogs.

```sh
sudo dnf install snodec mqttsuite
```

## Configure and run

Inspect `mqttbroker --help`, `mqttcli --help` and `snodec-control --help`. Configure listeners, credentials and TLS certificates before starting services. The store requires a configured database. Consult the [application documentation](https://github.com/SNodeC/mqttsuite#project-overview) and [framework documentation](https://github.com/SNodeC/snode.c#project-overview) for options.

Executables are installed in `/usr/bin`. Administrative configuration lives in `/etc/snode.c`; non-root processes use their per-user configuration directories. Installation creates the `snodec` system group but does not start network services. To start a foreground broker:

```sh
mqttbroker --daemonize=false
```

For persistent operation, configure a systemd service with the desired user and arguments; these packages do not supply systemd service units.

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
baseurl=https://raw.githubusercontent.com/SNodeC/Packages/main/fedora/$releasever/$basearch/
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-snodec
REPO
sudo dnf makecache
```

The quoted `REPO` delimiter preserves `$releasever` and `$basearch`; DNF expands them for the installed system. Both RPM packages and repository metadata are signature-checked.

Then [choose packages](#choose-packages) to install.

## Reference

<details>
<summary>Supported releases, package architectures and indexes</summary>

### 43

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| 43 | `aarch64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/fedora/43/aarch64/repodata/repomd.xml) | [Browse](https://github.com/SNodeC/Packages/tree/main/fedora/43/aarch64) |
| 43 | `x86_64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/fedora/43/x86_64/repodata/repomd.xml) | [Browse](https://github.com/SNodeC/Packages/tree/main/fedora/43/x86_64) |

### 44

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| 44 | `aarch64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/fedora/44/aarch64/repodata/repomd.xml) | [Browse](https://github.com/SNodeC/Packages/tree/main/fedora/44/aarch64) |
| 44 | `x86_64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/fedora/44/x86_64/repodata/repomd.xml) | [Browse](https://github.com/SNodeC/Packages/tree/main/fedora/44/x86_64) |

</details>

## Troubleshooting

See [common problems and fixes](troubleshooting.md) for download, signature, dependency and application errors.

| Symptom | What to check |
| --- | --- |
| DNF selects the wrong release | Check `VERSION_ID` and DNF’s `$releasever`; do not mix Fedora release repositories. |

<p align="center">
  <a href="#fedora" title="Back to top"><img src="media/menu/back-to-top-124.svg" alt="Back to top" width="124" height="24"></a>
  <a href="../README.md#distributions" title="All distributions"><img src="media/menu/all-distributions-124.svg" alt="All distributions" width="124" height="24"></a>
  <a href="https://github.com/SNodeC/Packages/blob/main/docs/status.md#fedora" title="Package status"><img src="media/menu/package-status-124.svg" alt="Package status" width="124" height="24"></a>
</p>
