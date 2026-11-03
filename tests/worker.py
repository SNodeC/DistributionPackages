"""Focused public-boundary checks for SNodeC deployment interoperability."""

import copy
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_ci"))
from native_container import package
from contract import package_metadata, versions
from status_update import projection, snapshot

TEMP = Path("/tmp/codex/build/core-ci/worker-interoperability")
TEMP.mkdir(parents=True, exist_ok=True)


def work(identity, index, tag, state, prerequisites):
    return {
        "id": identity, "index": index, "source": {"repository": "SNodeC/snode.c", "tag": tag},
        "target": {"id": "debian-trixie-amd64", "distribution": "debian", "suite": "trixie", "arch": "amd64",
                   "build": {"format": "deb"}},
        "prerequisites": prerequisites, "active": {"id": identity + "-attempt", "revision": index + 1, "state": state},
    }


class Worker(unittest.TestCase):
    def test_initial_stream_and_presentation(self):
        graph = {"repositories": {"SNodeC/snode.c": {"definition": {"title": "SNode.C", "matrix": [
            {"distribution": "debian", "suite": "trixie", "arch": "amd64", "build": {"format": "deb"}},
        ]}}}, "executions": {}, "ready": False}
        records = [work("core/~", 0, "v2.10.0", "building", []),
                   work("later", 1, "v2.9.0", "waiting", ["core/~"])]
        messages = [graph]
        for record in records:
            token = record["id"].replace("~", "~0").replace("/", "~1")
            messages.append([{"op": "add", "path": "/executions/" + token, "value": record}])
        messages.append([{"op": "replace", "path": "/ready", "value": True}])
        wire = b": heartbeat\n\n" + b"".join(b"data: " + json.dumps(value).encode() + b"\n\n" for value in messages)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(wire)

            def log_message(self, *arguments):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            actual = snapshot("http://127.0.0.1:" + str(server.server_port) + "/events")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        self.assertTrue(actual["ready"])
        self.assertEqual(actual["executions"], {record["id"]: record for record in records})
        os.environ.update(FEED_REPOSITORY="SNodeC/Packages", FEED_REPOSITORY_ID="1404446502", FEED_BRANCH="main")
        facts = projection(actual)
        self.assertEqual(facts["projects"][0]["versions"], ["v2.10.0", "v2.9.0"])
        self.assertEqual(facts["executions"][0]["blockers"], ["core/~"])
        self.assertIsNone(facts["executions"][0]["publication_verified_utc"])
        retired = copy.deepcopy(actual)
        retired["executions"]["later"]["active"]["retirement"] = {"remote_outcome": "unknown"}
        self.assertEqual(projection(retired)["executions"][0]["activity"], "Retired")

    def test_real_cpack_deb_and_rpm(self):
        with tempfile.TemporaryDirectory(dir=TEMP) as temporary:
            root = Path(temporary)
            (root / "payload").write_text("isolated CPack fixture\n")
            (root / "PackageConfig.cmake").write_text(
                'set(CPACK_DEBIAN_FULL_PACKAGE_DEPENDS "snodec-common (= ${CPACK_PACKAGE_VERSION})")\n'
                'set(CPACK_RPM_FULL_PACKAGE_REQUIRES "snodec-common = ${CPACK_PACKAGE_VERSION}-${CPACK_RPM_PACKAGE_RELEASE}")\n'
            )
            (root / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.20)\nproject(snodec_fixture VERSION 3.0.0 LANGUAGES NONE)\n"
                "install(FILES payload DESTINATION share/snodec COMPONENT common)\n"
                "install(FILES payload DESTINATION share/snodec/full COMPONENT full)\n"
                "set(CPACK_PACKAGE_NAME snodec)\nset(CPACK_PACKAGE_VERSION 3.0.0)\n"
                "set(CPACK_PACKAGE_DESCRIPTION_SUMMARY \"isolated fixture\")\n"
                "set(CPACK_PACKAGE_CONTACT fixture@example.invalid)\n"
                "set(CPACK_DEBIAN_PACKAGE_MAINTAINER fixture)\nset(CPACK_RPM_PACKAGE_LICENSE MIT)\n"
                "set(CPACK_DEB_COMPONENT_INSTALL ON)\nset(CPACK_RPM_COMPONENT_INSTALL ON)\n"
                "set(CPACK_COMPONENTS_GROUPING IGNORE)\nset(CPACK_DEBIAN_FULL_PACKAGE_NAME snodec)\n"
                "set(CPACK_RPM_FULL_PACKAGE_NAME snodec)\n"
                'set(CPACK_PROJECT_CONFIG_FILE "${CMAKE_CURRENT_SOURCE_DIR}/PackageConfig.cmake")\ninclude(CPack)\n'
            )
            build = root / "build"
            subprocess.run(["cmake", "-S", str(root), "-B", str(build)], check=True)
            for kind in ("deb", "rpm"):
                with self.subTest(format=kind):
                    destination = root / kind
                    destination.mkdir()
                    target = root / "target.json"
                    target.write_text(json.dumps({"build": {"format": kind}}))
                    os.environ.update(TARGET_JSON=str(target), OUTPUT_DIR=str(destination),
                                      SOURCE_VERSION="v3.0.0", PACKAGE_REVISION="7")
                    package(str(build))
                    declared = json.loads((destination / "outputs.json").read_text())
                    self.assertEqual(len(declared["packages"]), 2)
                    for item in declared["packages"]:
                        actual = package_metadata(destination / item["file"], kind)
                        self.assertEqual(actual["version"], versions("v3.0.0", 7, kind)["full"])
                        self.assertEqual(actual["name"], item["component"])
                        if actual["name"] == "snodec":
                            self.assertIn(versions("v3.0.0", 7, kind)["full"], str(actual["dependencies"]))


if __name__ == "__main__":
    unittest.main()
