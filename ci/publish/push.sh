#!/usr/bin/env bash
# Reapply the operation after a competing commit; never overwrite a newer snapshot.
set -euo pipefail
root=$(realpath "$1")
message=$2
shift 2
git -C "$root" config user.name 'github-actions[bot]'
git -C "$root" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
for attempt in {1..30}; do
    git -C "$root" fetch --quiet origin main
    previous=$(git -C "$root" rev-parse FETCH_HEAD)
    git -C "$root" reset --hard "$previous" >/dev/null
    git -C "$root" clean -fd >/dev/null
    result=0
    "$@" || result=$?
    # Exit 2 means a validated publication failure was recorded for display.
    if [ "$result" != 0 ] && [ "$result" != 2 ]; then exit "$result"; fi
    git -C "$root" add .
    if git -C "$root" diff --cached --quiet; then exit "$result"; fi
    snapshot=$(git -C "$root" commit-tree "$(git -C "$root" write-tree)" -m "$message")
    if git -C "$root" push --force-with-lease="refs/heads/main:$previous" origin "$snapshot:refs/heads/main"; then
        git -C "$root" reset --hard "$snapshot" >/dev/null
        exit "$result"
    fi
    remote=$(git -C "$root" ls-remote origin refs/heads/main | cut -f1)
    if [ "$remote" = "$snapshot" ]; then exit "$result"; fi
    if [ "$remote" = "$previous" ]; then exit 1; fi
    sleep "$((RANDOM % 3 + 1))"
done
echo 'Snapshot changed repeatedly; no update committed' >&2
exit 1
