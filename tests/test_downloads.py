"""Shared transport retries preserve capture, validation and filesystem boundaries."""
from email.message import Message
import http.client
import io
import json
import socket
import ssl
import tempfile
from pathlib import Path
import unittest
from support import PinnedJsonCase
from unittest.mock import call, patch
import urllib.error

from ci import repository


def response(body=b'complete', length=None):
    stream = io.BytesIO(body)
    stream.headers = {'Content-Length': str(len(body) if length is None else length)}
    return stream


def http_error(code, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers['Retry-After'] = retry_after
    return urllib.error.HTTPError('https://example.invalid/package', code, 'failure', headers, None)


class DownloadTest(PinnedJsonCase):
    def test_metadata_and_file_use_one_transport_with_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'package'
            path.write_bytes(b'previous')
            with patch.object(repository.urllib.request, 'urlopen', side_effect=[response(), response()]) as opened:
                with patch.object(repository.time, 'sleep') as sleep:
                    self.assertEqual(repository.fetch('https://example.invalid/metadata'), b'complete')
                    self.assertIsNone(repository.fetch('https://example.invalid/package', path))
            self.assertEqual(path.read_bytes(), b'complete')
            self.assertEqual(list(Path(directory).iterdir()), [path])
            self.assertEqual(opened.call_args_list, [call('https://example.invalid/metadata', timeout=120),
                                                    call('https://example.invalid/package', timeout=120)])
            sleep.assert_not_called()

    def test_transient_errors_retry_with_exact_backoff(self):
        errors = [ConnectionResetError('reset'), ConnectionAbortedError('aborted'), TimeoutError('timeout'),
                  urllib.error.URLError(ConnectionResetError('wrapped reset')),
                  urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, 'temporary DNS failure')),
                  http.client.IncompleteRead(b'partial', 5)]
        errors += [http_error(code) for code in (429, 502, 503, 504)]
        for error in errors:
            with self.subTest(error=repr(error)):
                with patch.object(repository.urllib.request, 'urlopen', side_effect=[error] * 3 + [response()]) as opened:
                    with patch.object(repository.time, 'sleep') as sleep:
                        self.assertEqual(repository.fetch('https://example.invalid/package'), b'complete')
                self.assertEqual(opened.call_count, 4)
                self.assertEqual(sleep.call_args_list, [call(60), call(300), call(900)])

    def test_exhaustion_preserves_destination_and_original_exception(self):
        error = urllib.error.URLError(ConnectionResetError('reset'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'package'
            path.write_bytes(b'previous')
            with patch.object(repository.urllib.request, 'urlopen', side_effect=error) as opened:
                with patch.object(repository.time, 'sleep') as sleep:
                    with self.assertRaises(urllib.error.URLError) as caught:
                        repository.fetch('https://example.invalid/package', path)
            self.assertIs(caught.exception, error)
            self.assertEqual(opened.call_count, 4)
            self.assertEqual(sleep.call_args_list, [call(60), call(300), call(900)])
            self.assertEqual(path.read_bytes(), b'previous')
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_nontransient_failures_stop_immediately(self):
        errors = [http_error(code) for code in (400, 401, 403, 404, 500)]
        errors += [urllib.error.URLError(ssl.SSLCertVerificationError('untrusted certificate')),
                   urllib.error.URLError(socket.gaierror(socket.EAI_NONAME, 'unknown host')),
                   urllib.error.URLError('unclassified transport failure'),
                   PermissionError('permission denied'), OSError(28, 'disk full')]
        for error in errors:
            with self.subTest(error=repr(error)):
                with patch.object(repository.urllib.request, 'urlopen', side_effect=error) as opened:
                    with patch.object(repository.time, 'sleep') as sleep:
                        with self.assertRaises(type(error)) as caught:
                            repository.fetch('https://example.invalid/package')
                self.assertIs(caught.exception, error)
                opened.assert_called_once()
                sleep.assert_not_called()

    def test_retry_after_seconds_dates_caps_and_fallbacks(self):
        cases = [('120', 120), ('0', 0), ('99999', 1800),
                 ('Thu, 01 Jan 1970 00:02:00 GMT', 120),
                 ('Thu, 01 Jan 1970 01:00:00 GMT', 1800),
                 ('Wed, 31 Dec 1969 23:59:00 GMT', 0),
                 ('Thu, 01 Jan 1970 00:02:00', 60),
                 ('invalid', 60), ('-1', 60), ('1.5', 60), ('', 60), (None, 60)]
        for code in (429, 503):
            for header, expected in cases:
                with self.subTest(code=code, header=header):
                    with patch.object(repository.urllib.request, 'urlopen', side_effect=[http_error(code, header), response()]):
                        with patch.object(repository.time, 'time', return_value=0):
                            with patch.object(repository.time, 'sleep') as sleep:
                                repository.fetch('https://example.invalid/package')
                    sleep.assert_called_once_with(expected)

    def test_missing_retry_after_preserves_each_backoff(self):
        with patch.object(repository.urllib.request, 'urlopen', side_effect=[http_error(429)] * 3 + [response()]):
            with patch.object(repository.time, 'sleep') as sleep:
                repository.fetch('https://example.invalid/package')
        self.assertEqual(sleep.call_args_list, [call(60), call(300), call(900)])

    def test_interrupted_and_short_transfers_are_cleaned_before_retry(self):
        class Interrupted(io.BytesIO):
            headers = {}

            def read(self, size=-1):
                if self.tell():
                    raise ConnectionResetError('mid-transfer reset')
                return super().read(size)

        for partial in (Interrupted(b'partial'), response(b'partial', length=100)):
            with self.subTest(partial=type(partial).__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'package'
                path.write_bytes(b'previous')

                def cleaned_before_sleep(delay):
                    self.assertEqual(delay, 60)
                    self.assertEqual(path.read_bytes(), b'previous')
                    self.assertEqual(list(Path(directory).iterdir()), [path])

                with patch.object(repository.urllib.request, 'urlopen', side_effect=[partial, response()]):
                    with patch.object(repository.time, 'sleep', side_effect=cleaned_before_sleep):
                        repository.fetch('https://example.invalid/package', path)
                self.assertEqual(path.read_bytes(), b'complete')
                self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_destination_write_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'package'
            with patch.object(repository.urllib.request, 'urlopen', return_value=response()) as opened:
                with patch.object(repository.os, 'replace', side_effect=OSError(28, 'disk full')):
                    with patch.object(repository.time, 'sleep') as sleep:
                        with self.assertRaises(OSError):
                            repository.fetch('https://example.invalid/package', path)
            opened.assert_called_once()
            sleep.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_dependency_checksum_failure_is_never_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / 'bundle'
            bundle.mkdir()
            (bundle / 'profiles.json').write_text(json.dumps({'linux-test': {'directory': 'feed',
                                                                          'context': {'packages_commit': 'captured'}}}))
            (bundle / 'targets.json').write_text(json.dumps([{'id': 'linux-test', 'family': 'linux',
                                                            'distribution': 'fedora', 'suite': '44'}]))
            (bundle / 'baseline.json').write_text(json.dumps({'sources': {'snode.c': {'refs/tags/v1.0.0': 'a' * 40}},
                                                             'files': {'snodec-test.rpm': 'wrong checksum'}}))
            (bundle / 'context.json').write_text(json.dumps({'build_project': 'mqttsuite'}))
            with patch.dict(repository.os.environ, {'PUBLISHED_REF': ''}):
                with patch.object(repository.urllib.request, 'urlopen', return_value=response()) as opened:
                    with patch.object(repository.time, 'sleep') as sleep:
                        with self.assertRaisesRegex(RuntimeError, 'Published dependency checksum mismatch'):
                            repository.reuse(bundle, 'linux-test', root / 'dependencies')
            opened.assert_called_once_with('https://raw.githubusercontent.com/SNodeC/Packages/captured/feed/snodec-test.rpm',
                                           timeout=120)
            sleep.assert_not_called()
        return None

    def test_sdk_checksum_failure_is_never_retried_or_extracted(self):
        row = {'release': '25.12.5', 'target': 'test/target', 'arch': 'test_arch'}
        with tempfile.TemporaryDirectory() as directory:
            profile = response(json.dumps({'arch_packages': 'test_arch'}).encode())
            checksums = response(b'wrong-checksum openwrt-sdk-test.tar.xz\n')
            with patch.object(repository.urllib.request, 'urlopen', side_effect=[profile, checksums, response()]) as opened:
                with patch.object(repository.time, 'sleep') as sleep, patch.object(repository, 'run') as run:
                    with self.assertRaisesRegex(RuntimeError, 'SDK checksum mismatch'):
                        repository.download_sdk(row, Path(directory) / 'sdk')
            self.assertEqual(opened.call_count, 3)
            sleep.assert_not_called()
            run.assert_not_called()
