"""Run package tests and actual source contracts with local-only transport."""
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class Counts(unittest.TextTestResult):
    def addSuccess(self, test):
        super().addSuccess(test)
        self.successes = getattr(self, 'successes', 0) + 1
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--actionlint', required=True)
    parser.add_argument('sources', nargs=3, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    checkouts = [root, *args.sources]
    before = {str(p): subprocess.check_output(['git','status','--porcelain','--untracked-files=all'], cwd=p) for p in checkouts}
    result, checks = 0, []
    with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as temporary:
        definitions = Path(temporary)/'definitions.json'
        shutil.copy2(root/'tests/fixtures/projects.json', definitions)
        os.environ.update(CI_DEFINITIONS=str(definitions), PYTHONDONTWRITEBYTECODE='1', GIT_ALLOW_PROTOCOL='file')
        import offline
        from ci import repository
        suite = unittest.defaultTestLoader.discover(str(root/'tests'))
        outcome = unittest.TextTestRunner(verbosity=2, resultclass=Counts).run(suite)
        result = int(not outcome.wasSuccessful())
        try:
            graph = {p.parent.name: json.loads((p/'ci/packages.json').read_text()) for p in args.sources}
            repository.validate_projects(graph)
            for source in args.sources:
                for hook in graph[source.parent.name]['build'].values():
                    assert (source/hook).is_file(), hook
            checks.append(dict(command='source JSON and hook contracts', returncode=0))
        except (AssertionError, ValueError, KeyError, TypeError, OSError) as error:
            print('SOURCE CONTRACT FAILURE', error, flush=True)
            checks.append(dict(command='source JSON and hook contracts', returncode=1, reason=str(error)))
            result = 1
        wrappers = [p/'.github/workflows/build-distribution-packages.yml' for p in args.sources]
        commands = [[sys.executable, str(root/'tests/check_package_workflows.py'), *map(str, wrappers)]]
        commands += [[args.actionlint, '-ignore', 'missing input "app-id".*actions/create-github-app-token@v3',
                      '-ignore', 'input "client-id" is not defined.*actions/create-github-app-token@v3',
                      '-ignore', 'unexpected key "queue" for "concurrency"',
                      '-ignore', 'property "workflow_(repository|sha)" is not defined in object type', *map(str, (root/'.github/workflows').glob('*.yml'))]]
        commands += [[args.actionlint, str(wrapper)] for wrapper in wrappers]
        for checkout in checkouts:
            if checkout != root:
                commands += [[sys.executable, str(path)] for path in sorted((checkout/'tests/ci').glob('test_*.py'))]
            for path in (checkout/'ci').rglob('*'):
                if path.suffix == '.sh':
                    commands.append(['bash','-n',str(path)])
                elif path.suffix == '.py':
                    try:
                        ast.parse(path.read_text(), filename=str(path))
                        checks.append(dict(command='Python syntax: ' + str(path), returncode=0))
                    except (SyntaxError, OSError) as error:
                        checks.append(dict(command='Python syntax: ' + str(path), returncode=1, reason=str(error)))
                        result = 1
        for command in commands:
            print('CHECK', ' '.join(command), flush=True)
            code = subprocess.run(command, cwd=root).returncode
            checks.append(dict(command=command, returncode=code))
            result |= int(code != 0)
    for checkout in checkouts:
        assert subprocess.check_output(['git','status','--porcelain','--untracked-files=all'], cwd=checkout) == before[str(checkout)], 'Checks changed '+str(checkout)
    if os.environ.get('PACKAGE_TEST_RESULTS'):
        Path(os.environ['PACKAGE_TEST_RESULTS']).write_text(json.dumps(dict(tests=outcome.testsRun,
            passed=getattr(outcome, 'successes', 0), failures=len(outcome.failures), errors=len(outcome.errors),
            skips=[dict(test=str(test), reason=reason) for test, reason in outcome.skipped], checks=checks, exit_code=result), indent=2) + '\n')
    return result


if __name__ == '__main__':
    sys.exit(main())
