#!/usr/bin/env bash
# Shared metadata transaction: allocation is required; status delivery is best-effort.
set -euo pipefail
root=$1
command=$2
shift 2
[ "$command" = reserve ] || trap 'result=$?; if [ "$result" != 0 ]; then echo "::warning::Package status update failed (exit $result); continuing"; fi; exit 0' EXIT
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
for attempt in {1..30}; do
    git -C "$root" fetch --quiet origin main
    previous=$(git -C "$root" rev-parse FETCH_HEAD)
    git -C "$root" reset --hard "$previous" >/dev/null
    git -C "$root" clean -fd >/dev/null
    python3 -m ci.publish.publication "$command" "$root" "$@"
    git -C "$root" add .
    if git -C "$root" diff --cached --quiet; then exit 0; fi
    snapshot=$(git -C "$root" commit-tree "$(git -C "$root" write-tree)" -p "$previous" -m "Package status: $command")
    if git -C "$root" push --force-with-lease="refs/heads/main:$previous" origin "$snapshot:refs/heads/main"; then
        git -C "$root" reset --hard "$snapshot" >/dev/null
        exit 0
    fi
    sleep "$((RANDOM % 5 + 1))"
done
echo '::warning::Package status update exhausted 30 attempts'
exit 1
