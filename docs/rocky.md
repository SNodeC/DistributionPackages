# Rocky Linux

[← All distributions](../README.md#distributions)

[Requirements](#requirements) · [Quick install](#quick-install) · [Choose packages](#choose-packages) · [Configure and run](#configure-and-run) · [Updates](#updates) · [Manual repository setup](#manual-repository-setup) · [Reference](#reference) · [Troubleshooting](#troubleshooting)

## Requirements

Supported releases: `9`, `10`. Match the release and package architecture installed on your device. Keep official repositories enabled for dependencies.

Use an account with `sudo`, or run administrative commands directly as root.
Install `curl` and CA certificates before downloading the installer.

```sh
. /etc/os-release
printf 'Distribution: %s\nRelease: %s\n' "$ID" "$VERSION_ID"
rpm --eval '%{_arch}'
```

```sh
sudo dnf install ca-certificates curl
```

Rocky Linux 10 requires x86-64-v3 on x86 systems. ARM64 packages use
`aarch64`. Enable CRB and EPEL before either installation method:

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

The installer detects the distribution, release and package architecture, checks
that an index exists, installs the signing key, configures the repository
and installs the complete package set. Configure applications before starting them.
Prefer manual setup? Use [Manual repository setup](#manual-repository-setup).

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

Dependencies are installed automatically. For the full selection after manual
preparation, install the complete-project packages listed below.

| Package | Contents |
| --- | --- |
| `snodec` | All framework components, headers, examples and configuration tool |
| `snodec-apps` | Demonstration applications |
| `snodec-control` | Component containing `snodec-control` |
| `mqttsuite` | All five applications and both mapping plugins |
| `mqttsuite-broker` | MQTT broker |
| `mqttsuite-cli` | Publish/subscribe command-line client |

See the complete [SNode.C](snodec-package-options.md) and
[MQTTSuite](mqttsuite-package-options.md) package catalogs.

```sh
sudo dnf install snodec mqttsuite
```

## Configure and run

Inspect `mqttbroker --help`, `mqttcli --help` and `snodec-control --help`. Configure
listeners, credentials and TLS certificates before starting services. The store
requires a configured database. Consult the [application documentation](https://github.com/SNodeC/mqttsuite#readme)
and [framework documentation](https://github.com/SNodeC/snode.c#readme) for options.

Executables are installed in `/usr/bin`. Administrative configuration lives in
`/etc/snode.c`; non-root processes use their per-user configuration directories.
Installation creates the `snodec` system group but does not start network services.
To start a foreground broker:

```sh
mqttbroker --daemonize=false
```

For persistent operation, configure a systemd service with the desired user and
arguments; these packages do not supply systemd service units.

## Updates

```sh
sudo dnf upgrade 'snodec*' 'mqttsuite*'
```

For selective installations, name the installed components rather than adding
the complete metapackages. After a distribution upgrade, configure the repository
for its new supported release and refresh metadata.

## Manual repository setup

These commands configure the signed repository without installing SNode.C or MQTTSuite.

APT and RPM repositories use the same signing key. Its download filename is
`snodec-apt.asc`; the commands below install it under the RPM-specific name
`RPM-GPG-KEY-snodec`.

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

The quoted `REPO` delimiter preserves `$releasever` and `$basearch`; DNF expands
them for the installed system. Both RPM packages and repository metadata are
signature-checked.

Then [choose packages](#choose-packages) to install.

## Reference

<details>
<summary>Supported releases, package architectures and indexes</summary>

### 9

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| 9 | `aarch64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/rocky/9/aarch64/repodata/repomd.xml) | [Browse](https://github.com/SNodeC/Packages/tree/main/rocky/9/aarch64) |
| 9 | `x86_64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/rocky/9/x86_64/repodata/repomd.xml) | [Browse](https://github.com/SNodeC/Packages/tree/main/rocky/9/x86_64) |

### 10

| Release | Package architecture | Index | Browse |
| --- | --- | --- | --- |
| 10 | `aarch64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/rocky/10/aarch64/repodata/repomd.xml) | [Browse](https://github.com/SNodeC/Packages/tree/main/rocky/10/aarch64) |
| 10 | `x86_64` | [Index](https://raw.githubusercontent.com/SNodeC/Packages/main/rocky/10/x86_64/repodata/repomd.xml) | [Browse](https://github.com/SNodeC/Packages/tree/main/rocky/10/x86_64) |

</details>

## Troubleshooting

See [common problems and fixes](troubleshooting.md) for download, signature,
dependency and application errors.

| Symptom | What to check |
| --- | --- |
| Dependencies are missing | Enable CRB and EPEL as shown in Requirements. |
| Illegal instruction on x86 | Check the x86-64-v3 requirement for Rocky Linux 10. |

[Back to top](#rocky-linux) · [All distributions](../README.md#distributions) · [Package status](https://github.com/SNodeC/Packages/blob/main/docs/status.md#rocky-linux)
