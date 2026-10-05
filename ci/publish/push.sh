#!/usr/bin/env bash
# Feed writers are serialized; only status commits may be merged on a lease conflict.
set -euo pipefail
root=$1
previous=$2
message=$3
shift 3
git -C "$root" config user.name 'github-actions[bot]'
git -C "$root" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
for attempt in {1..30}; do
    if [ "$#" != 0 ]; then "$@"; fi
    git -C "$root" add .
    if git -C "$root" diff --cached --quiet; then exit 0; fi
    snapshot=$(git -C "$root" commit-tree "$(git -C "$root" write-tree)" -m "$message")
    if git -C "$root" push --force-with-lease="refs/heads/main:$previous" origin "$snapshot:refs/heads/main"; then
        exit 0
    fi
    git -C "$root" fetch --quiet origin main
    remote=$(git -C "$root" rev-parse FETCH_HEAD)
    if [ "$remote" = "$snapshot" ]; then exit 0; fi
    if [ "$remote" = "$previous" ]; then exit 1; fi
    if ! git -C "$root" diff --quiet "$previous" "$remote" -- . ':!status.json' ':!docs/status.md' ':!status'; then
        echo 'Remote feed changed; refusing to replace it' >&2
        exit 1
    fi
    git -C "$root" rm -rf --ignore-unmatch -- status.json docs/status.md status/ >/dev/null
    git -C "$root" ls-tree -r --name-only -z "$remote" -- status.json docs/status.md status/ |
        xargs -0 -r git -C "$root" checkout "$remote" --
    previous=$remote
    sleep "$((RANDOM % 5 + 1))"
done
echo 'Status writes kept changing the snapshot; publication not pushed' >&2
exit 1
