"""Local navigation fixture and a transport guard, also used by CLI subprocesses."""
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

_original = subprocess.run


def offline(args, **kwargs):
    if 'https://github.com/SNodeC/.github.git' in args and 'clone' in args:
        destination = Path(args[-1])
        source = Path(os.environ['SNODEC_TEST_TOOLING'])
        for name in ('tools', 'navigation', 'brand'):
            shutil.copytree(source / name, destination / name)
        shutil.copy2(source / 'catalog.yml', destination / 'catalog.yml')
        result = subprocess.CompletedProcess(args, 0)
    elif len(args) > 3 and args[1] == '-C' and args[3] == 'sparse-checkout' and not (Path(args[2]) / '.git').exists():
        result = subprocess.CompletedProcess(args, 0)
    else:
        command = Path(str(args[0])).name
        if command == 'gh' or command == 'git' and any(
                '://' in str(a) and not str(a).startswith('file://') or str(a).startswith('git@') for a in args):
            raise AssertionError('Live GitHub transport forbidden in package tests: ' + str(args))
        if command in {'pip', 'pip3'} or command.startswith('python') and list(args[1:3]) == ['-m', 'pip']:
            raise AssertionError('Tool installation forbidden in package tests: ' + str(args))
        try:
            result = _original(args, **kwargs)
        except subprocess.CalledProcessError as error:
            if error.stderr:
                print(error.stderr.decode() if isinstance(error.stderr, bytes) else error.stderr, file=sys.stderr)
            raise
    return result


subprocess.run = offline
if __name__ == '__main__':
    mode = sys.argv[1]
    sys.argv = sys.argv[2:]
    if mode == '-m':
        runpy.run_module(sys.argv[0], run_name='__main__')
    elif mode == '-c':
        exec(sys.argv[0], {'__name__':'__main__'})
    else:
        raise AssertionError('Unexpected test Python invocation: ' + mode)
