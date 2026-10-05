# Package status

To install, see [Quick start](https://github.com/SNodeC/Packages/blob/main/README.md#quick-start).

## Reading the matrix

**Version** is what is available to install. **Status** describes the latest
build attempt; click its badge to inspect the job (repository access required for private build logs). An unfinished or failed rebuild
does not replace an available version. A dash means no version is recorded.

<details>
<summary>Status legend and links</summary>

- **Pending:** waiting to build or publish.
- **Running:** building and testing.
- **Built:** build and tests succeeded; waiting for publication.
- **Publishing:** assembling and pushing the package snapshot.
- **Published:** the packages have been pushed.
- **Failed**, **cancelled**, **skipped**, **superseded:** the attempt did not publish.
- **Not built:** neither a build result nor a published version is recorded.

Existing jobs synchronously push badges at preparation, build start, build exit
and publication. Force cancellation, runner loss or an unavailable publication
endpoint can prevent a final update. GitHub image
caching can delay display after an update.
**Published** shows the feed's latest publication date in UTC; click the date
for the full timestamp and source record. Either project's publication can update
that date. **Packages** opens the shared package directory; package managers use
its signed index to select the current files.

</details>

## OpenWrt

[Installation guide](https://github.com/SNodeC/Packages/blob/main/docs/openwrt.md)

<!-- targets:openwrt -->

## Raspberry Pi OS

[Installation guide](https://github.com/SNodeC/Packages/blob/main/docs/raspberrypi.md)

<!-- targets:raspberrypios -->

## Debian

[Installation guide](https://github.com/SNodeC/Packages/blob/main/docs/debian.md)

<!-- targets:debian -->

## Ubuntu

[Installation guide](https://github.com/SNodeC/Packages/blob/main/docs/ubuntu.md)

<!-- targets:ubuntu -->

## Rocky Linux

[Installation guide](https://github.com/SNodeC/Packages/blob/main/docs/rocky.md)

<!-- targets:rocky -->

## Fedora

[Installation guide](https://github.com/SNodeC/Packages/blob/main/docs/fedora.md)

<!-- targets:fedora -->

## Help

[Troubleshooting](https://github.com/SNodeC/Packages/blob/main/docs/troubleshooting.md) · [Repository maintenance](https://github.com/SNodeC/Packages/blob/main/docs/maintainers.md) · [Back to installation](https://github.com/SNodeC/Packages/blob/main/README.md#quick-start)
