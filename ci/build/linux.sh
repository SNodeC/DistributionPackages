#!/usr/bin/env bash
set -euo pipefail
row=$1
readarray -t fields < <(python3 - "$row" <<'PY'
import json, sys
row = json.loads(sys.argv[1])
for key in ['distribution', 'suite', 'arch', 'platform', 'image']:
    print(row[key])
PY
)
export DISTRIBUTION=${fields[0]} SUITE=${fields[1]} ARCH=${fields[2]}
platform=${fields[3]}
image=${fields[4]}
mkdir -p packages output logs
docker pull --platform "$platform" "$image"
container=(docker run --rm --network host --platform "$platform" -v "$PWD:/work" -w /work
    -e DISTRIBUTION -e SUITE -e ARCH -e PACKAGE_RELEASE -e BUILD_PROJECT)
"${container[@]}" "$image" bash /work/feed/ci/build/native.sh 2>&1 | tee logs/build.log
sudo chown -R "$(id -u):$(id -g)" packages
python3 -m ci.publish.linux stage "$row" packages bundle output
sudo chown -R "$(id -u):$(id -g)" output logs
