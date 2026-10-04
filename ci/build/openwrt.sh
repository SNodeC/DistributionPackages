#!/usr/bin/env bash
set -euo pipefail
feed=$(realpath "$1")
export PYTHONPATH="$feed"
bundle=$(realpath "$2")
sdk=$(realpath "$3")
: "${PACKAGE_RELEASE:?}" "${OPENWRT_USIGN_KEY:?}" "${OPENWRT_APK_KEY:?}"
python3 -m ci.repository check "$bundle"
cd "$sdk"
umask 077
printf '%s\n' "$OPENWRT_USIGN_KEY" > key-build
printf '%s\n' "$OPENWRT_APK_KEY" > private-key.pem
unset OPENWRT_USIGN_KEY OPENWRT_APK_KEY
trap 'rm -f key-build private-key.pem' EXIT
umask 022
cp "$feed/keys/snodec-usign.pub" key-build.pub
cp "$feed/keys/snodec-apk.pem" public-key.pem
# Archives include submodules and come from the captured tag pair.
mkdir -p dl
for package in "$BUILD_PROJECT"; do
    cp "$bundle/$package-"*.tar.gz dl/
done
export SNODEC_PACKAGE_RELEASE="$PACKAGE_RELEASE" MQTTSUITE_PACKAGE_RELEASE="$PACKAGE_RELEASE"
if [ "$BUILD_PROJECT" = snode.c ]; then
    export SNODEC_SOURCE_TAG=$(jq -r '.source_tags["snode.c"]' "$bundle/context.json")
    export SNODEC_PACKAGE_VERSION=$(jq -r '.versions["snode.c"]' "$bundle/context.json")
    export SNODEC_SOURCE_HASH=$(sha256sum "$bundle/snode.c-"*.tar.gz | cut -d' ' -f1)
else
    export MQTTSUITE_SOURCE_TAG=$(jq -r '.source_tags.mqttsuite' "$bundle/context.json")
    export MQTTSUITE_PACKAGE_VERSION=$(jq -r '.versions.mqttsuite' "$bundle/context.json")
    export MQTTSUITE_SOURCE_HASH=$(sha256sum "$bundle/mqttsuite-"*.tar.gz | cut -d' ' -f1)
fi
cp feeds.conf.default feeds.conf
printf '\nsrc-link snodec %s\n' "$feed" >> feeds.conf
./scripts/feeds update base packages snodec
./scripts/feeds install -a -p snodec
# Select publication packages; feature defaults come from their Config.in files.
cat > .config <<'EOF'
# CONFIG_ALL is not set
# CONFIG_ALL_NONSHARED is not set
# CONFIG_ALL_KMODS is not set
# CONFIG_AUTOREMOVE is not set
CONFIG_SIGNED_PACKAGES=y
CONFIG_PACKAGE_snodec=m
CONFIG_PACKAGE_mqttsuite=m
EOF
make defconfig
if [ "$BUILD_PROJECT" = snode.c ]; then
    make -j"$(nproc)" package/snode.c/compile V=s BUILD_LOG=1
    python3 "$feed/ci/build/openwrt-tests.py" "$sdk"
fi
python3 -m ci.repository sdk-dependency "$sdk" "$bundle" "$feed/../dependencies"
if [ "$BUILD_PROJECT" = mqttsuite ]; then
    # The matching SNode.C job has already published, or this is an application-only release.
    make -j"$(nproc)" MAKE="make -o package/feeds/snodec/snode.c/compile" package/mqttsuite/compile V=s BUILD_LOG=1
fi
arch=$(sed -n 's/^CONFIG_TARGET_ARCH_PACKAGES="\(.*\)"/\1/p' .config)
repository="bin/packages/$arch/snodec"
find "$feed/../dependencies" -maxdepth 1 -type f \( -name '*.ipk' -o -name '*.apk' \) -exec cp -t "$repository" {} +
make package/index V=s
if [ -f "$repository/packages.adb" ]; then
    staging_dir/host/bin/apk verify --keys-dir "$feed/keys" "$repository/packages.adb"
else
    staging_dir/host/bin/usign -V -p "$feed/keys/snodec-usign.pub" \
        -m "$repository/Packages" -x "$repository/Packages.sig"
fi
python3 -m ci.repository check "$bundle"
