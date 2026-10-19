#!/usr/bin/env bash
set -euo pipefail
feed=$(realpath "$1")
export PYTHONPATH="$feed"
bundle=$(realpath "$2")
sdk=$(realpath "$3")
: "${PACKAGE_RELEASE:?}"
python3 -m ci.repository check "$bundle"
cd "$sdk"
# Archives include submodules and come from the captured tag pair.
mkdir -p dl "recipes/$BUILD_PROJECT"
cp "$bundle/$BUILD_PROJECT-"*.tar.gz dl/
tar -xzf "$bundle/$BUILD_PROJECT-"*.tar.gz --wildcards --strip-components=4 \
    -C "recipes/$BUILD_PROJECT" "$BUILD_PROJECT-*/./*/openwrt/*"
python3 -m ci.repository sdk-dependency "$sdk" "$bundle" "$feed/../dependencies"
source "$feed/ci/recipes/$BUILD_PROJECT/openwrt.sh"
cp feeds.conf.default feeds.conf
printf '\nsrc-link snodec %s\n' "$sdk/recipes" >> feeds.conf
./scripts/feeds update base packages snodec
./scripts/feeds install -a -p snodec
# Select publication packages; feature defaults come from their Config.in files.
cat > .config <<EOF
# CONFIG_ALL is not set
# CONFIG_ALL_NONSHARED is not set
# CONFIG_ALL_KMODS is not set
# CONFIG_AUTOREMOVE is not set
# CONFIG_SIGNED_PACKAGES is not set
CONFIG_PACKAGE_$(python3 -c 'import os; from ci.repository import PROJECTS; print(PROJECTS[os.environ["BUILD_PROJECT"]]["package"])')=m
EOF
make defconfig
compile
arch=$(sed -n 's/^CONFIG_TARGET_ARCH_PACKAGES="\(.*\)"/\1/p' .config)
repository="bin/packages/$arch/snodec"
find "$feed/../dependencies" -maxdepth 1 -type f \( -name '*.ipk' -o -name '*.apk' \) -exec cp -t "$repository" {} +
make package/index V=s
python3 -m ci.repository check "$bundle"
