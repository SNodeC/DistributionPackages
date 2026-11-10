"""Retry only a confirmed competing feed push; resolve an ambiguous successful push."""
from datetime import datetime, timezone
import random
import shutil
import subprocess
import time
from pathlib import Path
import base64
import os
import re
from .contract import output, require, run


class LeaseConflict(Exception):
    pass


def push(root, branch, token, base):
    result = None
    started = time.monotonic()
    outcome = "error"
    print("push start " + datetime.now(timezone.utc).isoformat(), flush=True)
    try:
        objects = output(['git','-C',str(root),'rev-list','--objects','--exclude-promisor-objects','HEAD','--not',base])
        print(f"push objects {len(objects.splitlines())}", flush=True)
        result = checked_push(root, branch, token, base, timeout=600, progress=True)
        outcome = "success"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        subprocess.run(['git','-C',str(root),'fetch','--depth=1','--filter=blob:none','origin',branch],check=True)
        remote = output(['git','-C',str(root),'rev-parse','FETCH_HEAD'])
        local = output(['git','-C',str(root),'rev-parse','HEAD'])
        if remote == local:
            result = local
            outcome = "success"
        elif remote != base or isinstance(error, subprocess.TimeoutExpired):
            outcome = 'retry'
            raise LeaseConflict('feed lease changed or push timed out') from None
        else:
            raise
    finally:
        print(f"push end {datetime.now(timezone.utc).isoformat()} {time.monotonic() - started:.3f} {outcome}", flush=True)
    return result


def restore_full(root):
    subprocess.run(['git','-C',str(root),'reset','--hard','FETCH_HEAD'],check=True)
    subprocess.run(['git','-C',str(root),'clean','-fd'],check=True)
    return None


def restore_partial(root):
    subprocess.run(['git','-C',str(root),'update-ref','HEAD',output(['git','-C',str(root),'rev-parse','FETCH_HEAD'])],check=True)
    for path in Path(root).iterdir():
        if path.name != '.git':
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
    return None


def retry(root, operation, restore=restore_full):
    completed = False
    attempt = 0
    result = None
    while not completed and attempt < 5:
        attempt += 1
        try:
            result = operation()
            completed = True
        except LeaseConflict:
            if attempt == 5:
                raise
            restore(root)
            time.sleep(random.uniform(5,30))
    return result


def prepare_commit(feed, expected_paths, message="Publish verified core-ci packages", orphan=False, removed=()):
    base = output(["git", "-C", str(feed), "rev-parse", "--verify", "HEAD"]) if orphan else ""
    require(set(removed) <= set(expected_paths), "unapproved feed deletion")
    run(["git", "-C", str(feed), "add", "--all", "--", *expected_paths])
    staged_paths = output(["git", "-C", str(feed), "diff", "--cached", "--name-only", "--no-renames"]).splitlines()
    require(set(staged_paths) <= set(expected_paths), "feed index contains changes outside the prepared update")
    for path in expected_paths:
        if path in removed:
            require(not (feed / path).exists() and not (feed / path).is_symlink(), "deleted feed path still exists")
            run(["git", "-C", str(feed), "cat-file", "-e", "HEAD:" + path], stdout=subprocess.DEVNULL)
        else:
            raw = output(["git", "-C", str(feed), "hash-object", "--no-filters", str(feed / path)])
            staged = output(["git", "-C", str(feed), "rev-parse", ":" + path])
            require(raw == staged, "feed index omits or transforms verified package/index bytes")
    changed = subprocess.run(["git", "-C", str(feed), "diff", "--cached", "--quiet"], check=False).returncode
    require(changed in (0, 1), "cannot inspect feed changes")
    identity = ["git", "-C", str(feed), "-c", "user.name=core-ci publisher", "-c", "user.email=core-ci@users.noreply.github.com"]
    if orphan:
        snapshot = output(identity + ["commit-tree", output(["git", "-C", str(feed), "write-tree"]), "-m", message])
        run(["git", "-C", str(feed), "update-ref", "HEAD", snapshot, base])
    elif changed == 1:
        run(identity + ["commit", "-m", message], stdout=subprocess.DEVNULL)
    return base

def checked_push(feed, branch, token, base="", timeout=120, progress=False):
    authorization = base64.b64encode(("x-access-token:" + token).encode()).decode()
    environment = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + authorization,
        "GIT_TERMINAL_PROMPT": "0",
    }
    require(not base or re.fullmatch(r"[a-f0-9]{40}", base), "invalid expected feed head")
    lease = ["--force-with-lease=refs/heads/" + branch + ":" + base] if base else []
    run(
        ["git", "-C", str(feed), "push", *(["--progress"] if progress else []), *lease, "origin", "HEAD:refs/heads/" + branch],
        env=environment,
        timeout=timeout,
        stdout=subprocess.DEVNULL,
    )
    revision = output(["git", "-C", str(feed), "rev-parse", "HEAD"])
    return revision
