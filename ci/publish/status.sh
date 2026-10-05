#!/usr/bin/env bash
# Best-effort status events: never fail a build because Packages is unavailable.
set -euo pipefail
trap 'result=$?; if [ "$result" != 0 ]; then echo "::warning::Package status update failed (exit $result); continuing"; fi; exit 0' EXIT
root=$1
shift
if [ -n "${PACKAGES_TOKEN:-}" ]; then
    export GIT_CONFIG_COUNT=1
    export GIT_CONFIG_KEY_0=http.https://github.com/.extraheader
    export GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$PACKAGES_TOKEN" | base64 -w0)"
fi
if [ ! -d "$root/.git" ]; then
    git clone --filter=blob:none --no-checkout https://github.com/SNodeC/Packages.git "$root"
fi
git -C "$root" sparse-checkout set --no-cone /status.json /docs/status.md /status/ '**/build.json'
git -C "$root" config user.name 'github-actions[bot]'
git -C "$root" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
command=$1
shift
for attempt in {1..30}; do
    git -C "$root" fetch --quiet origin main
    previous=$(git -C "$root" rev-parse FETCH_HEAD)
    git -C "$root" reset --hard "$previous" >/dev/null
    git -C "$root" clean -fd >/dev/null
    python3 -m ci.publish.publication "$command" "$root" "$@"
    git -C "$root" add -- status.json docs/status.md status/
    if git -C "$root" diff --cached --quiet; then exit 0; fi
    snapshot=$(git -C "$root" commit-tree "$(git -C "$root" write-tree)" -m "Package status: $command")
    if git -C "$root" push --force-with-lease="refs/heads/main:$previous" origin "$snapshot:refs/heads/main"; then
        exit 0
    fi
    sleep "$((RANDOM % 5 + 1))"
done
echo '::warning::Package status update exhausted 30 attempts; continuing'
