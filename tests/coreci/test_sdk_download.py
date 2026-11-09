import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from support import environment
from coreci import sdk


class Download(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.archive = Path(self.temporary.name) / "sdk.tar.zst"
        self.content = b"verified SDK archive"
        self.environment = {"sdk": {"url": "https://downloads.openwrt.org/sdk.tar.zst",
                                   "sha256": hashlib.sha256(self.content).hexdigest()}}

    def transfer(self, command, **kwargs):
        self.assertEqual(command[command.index("--continue-at") + 1], "-")
        for flag, value in [("--retry", "5"), ("--connect-timeout", "30"),
                            ("--speed-limit", "1024"), ("--speed-time", "120"),
                            ("--retry-max-time", "5400")]:
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertIn("--retry-all-errors", command)
        self.assertIn("--location", command)
        self.assertLessEqual(kwargs["timeout"], 5400)
        self.assertGreaterEqual(kwargs["timeout"], 5390)
        Path(command[command.index("--output") + 1]).write_bytes(self.content)
        return subprocess.CompletedProcess(command, 0)

    def test_miss_and_verified_hit(self):
        with patch.object(sdk.subprocess, "run", side_effect=self.transfer) as run:
            self.assertEqual(sdk.acquire(self.environment, self.archive), self.archive)
            self.assertEqual(self.archive.read_bytes(), self.content)
            self.assertEqual(sdk.acquire(self.environment, self.archive), self.archive)
        self.assertEqual(run.call_count, 1)
        self.assertFalse(self.archive.with_name(self.archive.name + ".part").exists())

    def test_cache_mismatch_is_discarded_and_downloaded_again(self):
        self.archive.write_bytes(b"corrupted cached archive")
        def transfer(command, **kwargs):
            self.assertFalse(self.archive.exists())
            return self.transfer(command, **kwargs)
        with patch.object(sdk.subprocess, "run", side_effect=transfer):
            sdk.acquire(self.environment, self.archive)
        self.assertEqual(self.archive.read_bytes(), self.content)

    def test_cache_symlink_is_not_trusted(self):
        outside = self.archive.parent / "outside"
        outside.write_bytes(self.content)
        self.archive.symlink_to(outside)
        with patch.object(sdk.subprocess, "run", side_effect=self.transfer) as run:
            sdk.acquire(self.environment, self.archive)
        self.assertEqual(run.call_count, 1)
        self.assertFalse(self.archive.is_symlink())
        self.assertEqual(outside.read_bytes(), self.content)

    def test_bad_download_is_never_promoted_to_cache(self):
        def transfer(command, **kwargs):
            Path(command[command.index("--output") + 1]).write_bytes(b"incorrect bytes")
        with patch.object(sdk.subprocess, "run", side_effect=transfer):
            with self.assertRaisesRegex(ValueError, "SDK checksum mismatch"):
                sdk.acquire(self.environment, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertFalse(self.archive.with_name(self.archive.name + ".part").exists())

    def test_partial_failure_resumes_under_the_same_deadline(self):
        partial = self.archive.with_name(self.archive.name + ".part")
        calls = []
        def transfer(command, **kwargs):
            calls.append(kwargs["timeout"])
            if len(calls) == 1:
                partial.write_bytes(self.content[:8])
                raise subprocess.CalledProcessError(18, command)
            else:
                self.assertEqual(partial.read_bytes(), self.content[:8])
                self.transfer(command, **kwargs)
        with patch.object(sdk.subprocess, "run", side_effect=transfer), \
             patch.object(sdk.time, "monotonic", side_effect=[100, 100, 110]):
            sdk.acquire(self.environment, self.archive)
        self.assertEqual(calls, [5400, 5390])
        self.assertEqual(self.archive.read_bytes(), self.content)

    def test_timeout_keeps_partial_for_resumption_but_never_caches_it(self):
        partial = self.archive.with_name(self.archive.name + ".part")
        def timeout(command, **kwargs):
            partial.write_bytes(self.content[:8])
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        with patch.object(sdk.subprocess, "run", side_effect=timeout):
            with self.assertRaises(subprocess.TimeoutExpired):
                sdk.acquire(self.environment, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertEqual(partial.read_bytes(), self.content[:8])
        with patch.object(sdk.subprocess, "run", side_effect=self.transfer):
            sdk.acquire(self.environment, self.archive)
        self.assertEqual(self.archive.read_bytes(), self.content)

    def test_progress_cannot_extend_the_overall_deadline(self):
        def transfer(command, **kwargs):
            Path(command[command.index("--output") + 1]).write_bytes(self.content[:8])
            raise subprocess.CalledProcessError(18, command)
        with patch.object(sdk.subprocess, "run", side_effect=transfer) as run, \
             patch.object(sdk.time, "monotonic", side_effect=[0, 0, 5401]):
            with self.assertRaisesRegex(ValueError, "SDK download exceeded 90 minutes"):
                sdk.acquire(self.environment, self.archive)
        self.assertEqual(run.call_count, 1)
        self.assertFalse(self.archive.exists())

    def test_no_progress_failure_does_not_add_another_retry_policy(self):
        with patch.object(sdk.subprocess, "run", side_effect=subprocess.CalledProcessError(22, ["curl"])) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                sdk.acquire(self.environment, self.archive)
        self.assertEqual(run.call_count, 1)

    def test_actual_curl_continuation_sends_a_range_request(self):
        content = self.content
        offsets = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                offset = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
                offsets.append(offset)
                self.send_response(206 if offset else 200)
                if offset:
                    self.send_header("Content-Range", f"bytes {offset}-{len(content)-1}/{len(content)}")
                self.send_header("Content-Length", str(len(content) - offset))
                self.end_headers()
                self.wfile.write(content[:8] if len(offsets) == 1 else content[offset:])
                self.close_connection = True
            def log_message(self, *args):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        run = subprocess.run
        def transfer(command, **kwargs):
            # Emulate curl's retry exhaustion without waiting for its backoff.
            command = list(command)
            command[command.index("--retry") + 1] = "0"
            return run(command, capture_output=True, **kwargs)
        self.environment["sdk"]["url"] = f"http://127.0.0.1:{server.server_port}/sdk"
        try:
            with patch.object(sdk.subprocess, "run", side_effect=transfer):
                sdk.acquire(self.environment, self.archive)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        self.assertEqual(offsets, [0, 8])
        self.assertEqual(self.archive.read_bytes(), content)

    def test_existing_preparer_rechecks_even_a_cache_hit(self):
        self.archive.write_bytes(self.content)
        with environment({"CORECI_SDK_ARCHIVE": str(self.archive)}), \
             patch.object(sdk.subprocess, "run") as run, \
             patch.object(sdk, "prepare_sdk", return_value=("root", "staging")) as prepare:
            self.assertEqual(sdk.prepare("target", self.environment, self.archive.parent / "work"), ("root", "staging"))
        run.assert_not_called()
        prepare.assert_called_once_with("target", self.environment, self.archive.parent / "work", archive=self.archive)

    def test_native_targets_do_not_query_or_cache_an_sdk(self):
        with patch.object(sdk, "read_json", return_value={"entry": {"family": "native", "build": {"platform": "linux/amd64"}}}), \
             patch.object(sdk, "sdk") as metadata, patch.object(sdk, "github_outputs") as outputs:
            sdk.cache("manifest.json")
        metadata.assert_not_called()
        outputs.assert_called_once_with(emulator="")

    def test_build_cache_identity_matches_the_publisher(self):
        target = {"id": "t1", "family": "openwrt", "distribution": "openwrt", "suite": "24.10",
                  "arch": "x86_64", "build": {"release": "24.10.8", "format": "ipk"}}
        with patch.object(sdk, "read_json", return_value={"matrix": [target]}), \
             patch.object(sdk, "inputs", return_value={"target": "t1"}), \
             patch.object(sdk, "sdk", return_value=self.environment), \
             patch.object(sdk, "github_outputs") as outputs, environment({"RUNNER_TEMP": self.temporary.name}):
            sdk.cache()
        outputs.assert_any_call(archive=str(self.archive.parent / "coreci-sdk/sdk.tar.zst"),
                                       key="openwrt-sdk-sdk.tar.zst-" + self.environment["sdk"]["sha256"])

    def test_cache_identity_is_archive_only_and_shared_by_build_and_publish(self):
        target = {"family": "openwrt", "arch": "x86_64", "build": {"release": "24.10.8"}}
        with patch.object(sdk, "read_json", return_value={"entry": target}), \
             patch.object(sdk, "sdk", return_value=self.environment), \
             patch.object(sdk, "github_outputs") as outputs, environment({"RUNNER_TEMP": self.temporary.name}):
            sdk.cache("manifest.json")
        outputs.assert_any_call(archive=str(self.archive.parent / "coreci-sdk/sdk.tar.zst"),
                                       key="openwrt-sdk-sdk.tar.zst-" + self.environment["sdk"]["sha256"])
        workflow = Path(".github/workflows/coreci-build.yml").read_text()
        publisher = Path(".github/workflows/coreci-publish.yml").read_text()
        for text in [workflow, publisher]:
            self.assertIn("uses: actions/cache@v4", text)
            self.assertIn("path: ${{ steps.sdk.outputs.archive }}", text)
            self.assertIn("key: ${{ steps.sdk.outputs.key }}", text)
        self.assertIn("--manifest packages/manifest.json", publisher)


if __name__ == "__main__":
    unittest.main()
