"""Consumer validation against a locally served prepared feed, before pushing."""

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.request

from .common import download
from contract import file_hash, output, require


def native_script(entry, files, url, key):
    packages = " ".join(shlex.quote("/feed/" + p) for p in files if p.endswith((".deb", ".rpm")))
    base = url + entry["distribution"]
    if entry["build"]["format"] == "deb":
        source = f'deb [signed-by=/key/{key.name}] {base} {entry["suite"]} main\n'
        script = "set -euo pipefail\napt-get update\napt-get install -y ca-certificates gnupg\n"
        script += "printf %s " + shlex.quote(source) + " > /etc/apt/sources.list.d/coreci.list\n"
        script += ("apt-get update 2>&1 | tee /tmp/update.log\n"
                   "! grep -Ei 'NO_PUBKEY|not signed|signature.*(invalid|failed|could not)|GPG error' /tmp/update.log\n"
                   "packages=()\nfor p in " + packages + "; do\n"
                   "packages+=(\"$(dpkg-deb --field \"$p\" Package)=$(dpkg-deb --field \"$p\" Version)\")\ndone\n"
                   "apt-get install --dry-run \"${packages[@]}\"\n")
    else:
        source = (f'[coreci]\nname=coreci\nbaseurl={base}/{entry["suite"]}/{entry["arch"]}/\n'
                  f'gpgcheck=1\nrepo_gpgcheck=1\ngpgkey=file:///key/{key.name}\n')
        script = "set -euo pipefail\ndnf install -y dnf-plugins-core\n"
        script += "printf %s " + shlex.quote(source) + " > /etc/yum.repos.d/coreci.repo\n"
        script += ("dnf makecache --refresh\npackages=()\nfor p in " + packages + "; do\n"
                   "packages+=(\"$(rpm -qp --queryformat '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}' \"$p\")\")\ndone\n"
                   "dnf install -y --downloadonly \"${packages[@]}\"\n")
    return script


def rootfs(entry, directory):
    base = (f'https://downloads.openwrt.org/releases/{entry["build"]["release"]}/targets/'
            f'{entry["build"]["target"]}/')
    with urllib.request.urlopen(base + "sha256sums", timeout=60) as response:
        content = response.read(1024**2 + 1)
    require(len(content) <= 1024**2, "rootfs listing exceeds bound")
    matches = [line.split() for line in content.decode().splitlines()
               if len(line.split()) == 2 and line.split()[-1].endswith("-rootfs.tar.gz")]
    result = None
    if matches:
        checksum, name = min(matches, key=lambda item: item[1])
        name = name.lstrip("*")
        archive = directory / "rootfs.tar.gz"
        download(base + name, archive)
        require(file_hash(archive) == checksum, "rootfs checksum mismatch")
        # docker import preserves official rootfs links; the checksum authenticates the official archive.
        result = "coreci-validation:" + str(time.time_ns())
        subprocess.run(["docker", "import", str(archive), result], check=True, capture_output=True)
    return result


def validate(root, entry, files, key, sdk_root=None):
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        # Let the server bind port 0; publish its assigned port through a private file.
        port_file = work / "port"
        server_code = ("from http.server import HTTPServer,SimpleHTTPRequestHandler; "
                       "from functools import partial; from pathlib import Path; import sys; "
                       "s=HTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=sys.argv[1])); "
                       "Path(sys.argv[2]).write_text(str(s.server_port)); s.serve_forever()")
        server = subprocess.Popen([sys.executable, "-c", server_code, str(root), str(port_file)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        imported = None
        try:
            deadline = time.monotonic() + 10
            while not port_file.exists() and server.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            require(port_file.exists(), "local feed server failed")
            url = "http://127.0.0.1:" + port_file.read_text() + "/"
            if entry["family"] == "native":
                script = native_script(entry, files, url, key)
                image, platform = entry["build"]["image"], entry["build"]["platform"]
            else:
                imported = rootfs(entry, work)
                folder = root / "openwrt" / entry["suite"] / entry["arch"]
                fmt = entry["build"]["format"]
                if imported:
                    image, platform = imported, ""
                    repo = f'{url}openwrt/{entry["suite"]}/{entry["arch"]}'
                    script = openwrt_script(entry, repo, files, sdk_root, key, work)
                else:
                    sdk_verify(folder, fmt, sdk_root, key, work)
                    summary = Path(__import__("os").environ["GITHUB_STEP_SUMMARY"])
                    with summary.open("a") as stream:
                        stream.write(f'\n{entry["id"]}: no runnable official rootfs tarball; SDK signatures and index consistency verified.\n')
                    script = ""
            if script:
                args = ["docker", "run", "--rm", "--network=host"]
                if platform:
                    args += ["--platform", platform]
                args += ["--mount", f'type=bind,source={root},target=/feed,readonly', "--mount",
                         f'type=bind,source={key.parent},target=/key,readonly', image, "/bin/sh", "-c", script]
                # Native scripts need arrays and pipefail; all native build images provide bash.
                if entry["family"] == "native":
                    args[-3] = "/bin/bash"
                subprocess.run(args, check=True, timeout=1800)
        finally:
            server.terminate()
            server.wait(timeout=10)
            if imported:
                subprocess.run(["docker", "image", "rm", imported], check=False, capture_output=True)


def sdk_verify(folder, fmt, sdk, key, work):
    import gzip

    if fmt == "ipk":
        subprocess.run([str(sdk / "staging_dir/host/bin/usign"), "-V", "-m", str(folder / "Packages"),
                        "-p", str(key), "-x", str(folder / "Packages.sig")], check=True)
        require(gzip.decompress((folder / "Packages.gz").read_bytes()) == (folder / "Packages").read_bytes(),
                "opkg compressed index mismatch")
        tool = sdk / "scripts/ipkg-make-index.sh"
        actual = subprocess.check_output(["bash", str(tool), "."], cwd=folder,
                    env={**__import__("os").environ, "MKHASH": str(sdk / "staging_dir/host/bin/mkhash")})
        require(actual == (folder / "Packages").read_bytes(), "opkg index contents mismatch")
    else:
        tool = str(sdk / "staging_dir/host/bin/apk")
        subprocess.run([tool, "--keys-dir", str(key.parent), "verify", str(folder / "packages.adb")], check=True)
        for package in folder.glob("*.apk"):
            subprocess.run([tool, "--keys-dir", str(key.parent), "verify", str(package)], check=True)
        regenerated = work / "packages.adb"
        subprocess.run([tool, "--keys-dir", str(key.parent), "mkndx", "--output", str(regenerated),
                        *map(str, sorted(folder.glob("*.apk")))], check=True)
        published = output([tool, "adbdump", "--format", "json", str(folder / "packages.adb")])
        rebuilt = output([tool, "adbdump", "--format", "json", str(regenerated)])
        require(json.loads(published) == json.loads(rebuilt), "APK index contents mismatch")


def openwrt_script(entry, repo, files, sdk_root, key, work):
    fmt = entry["build"]["format"]
    # The caller supplies the OpenWrt public key, not the GPG development-export key.
    packages = " ".join(shlex.quote("/feed/" + p) for p in files if p.endswith("." + fmt))
    if fmt == "ipk":
        script = (f'set -eu\nmkdir -p -m 1777 /var/lock\nopkg-key add /key/{key.name}\nprintf %s '
                  + shlex.quote("src/gz coreci " + repo + "\n") + " >> /etc/opkg/customfeeds.conf\n"
                  + "opkg update\nopkg install --noaction " + packages)
    else:
        script = (f'set -eu\nmkdir -p /etc/apk/keys /etc/apk/repositories.d\ncp /key/{key.name} /etc/apk/keys/\n'
                  + "printf %s " + shlex.quote(repo + "/packages.adb\n") + " > /etc/apk/repositories.d/coreci.list\n"
                  + "apk update\napk add --simulate " + packages)
    return script
