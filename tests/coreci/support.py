"""Small fixtures and scoped replacements; no test framework."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@contextmanager
def replace(owner, name, value):
    previous = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, previous)


@contextmanager
def environment(values):
    previous = dict(os.environ)
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def rejects(function, *args, text='', **kwargs):
    caught = None
    try:
        function(*args, **kwargs)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        caught = error
    assert caught is not None, f'expected rejection from {function.__name__}'
    assert text in str(caught), f'expected {text!r}, got {caught!r}'


def registry_data():
    return {'build': 'Example/Recipes/.github/workflows/coreci-build.yml', 'default_feed': 'test',
            'repositories': ['Example/Source', 'Example/Other'], 'badges': 'https://badges.example/api/v1/badge',
            'feeds': {'test': {'publisher': 'Example/Recipes/.github/workflows/coreci-publish.yml',
                'repository': 'Example/Feed', 'url': 'https://feed.example/', 'environment': 'staging',
                'keys': {'gpg': {'file': 'keys/test.asc', 'fingerprint': 'A'*40},
                         'usign': {'file': 'keys/test.pub', 'key_id': '1234567890abcdef'},
                         'apk': {'file': 'keys/test.pem', 'sha256': '0'*64}}}}}


def build_inputs():
    return {'INPUT_BUILD_ID': 'a~t1~1.2.3-alpha+test~r7', 'INPUT_PACKAGE': 'a',
            'INPUT_VERSION': '1.2.3-alpha+test', 'INPUT_REVISION': '7', 'INPUT_TARGET': 't1',
            'INPUT_CALLBACK_URL': '', 'INPUT_SOURCE_REPO': 'Example/Source',
            'INPUT_TAG': 'v1.2.3-alpha+test', 'INPUT_PREREQUISITES': '', 'INPUT_RECIPE_REF': ''}


def entry(fmt='deb'):
    return {'id': 't1', 'family': 'native', 'distribution': 'debian' if fmt == 'deb' else 'fedora',
            'suite': 'stable', 'arch': 'amd64' if fmt == 'deb' else 'x86_64', 'runner': 'ubuntu-24.04',
            'build': {'format': fmt, 'image': 'example:stable', 'platform': 'linux/amd64'}}
