"""Retry only a confirmed competing feed push; resolve an ambiguous successful push."""
from datetime import datetime, timezone
import random
import shutil
import subprocess
import time
from pathlib import Path
from contract import output
from publish import checked_push


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
