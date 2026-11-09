"""Index and sign OpenWrt packages with verified SDK tools."""
import gzip
import os
import shutil
import subprocess
from .contract import run


def indexes(folder, package_format, sdk, tool, keys, private_key, public_key):
    if package_format == "ipk":
        index = folder / "Packages"
        with index.open("wb") as outgoing:
            subprocess.run(
                ["/bin/bash", str(sdk / "scripts/ipkg-make-index.sh"), "."],
                cwd=folder,
                env={**os.environ, "MKHASH": str(sdk / "staging_dir/host/bin/mkhash")},
                check=True,
                stdout=outgoing,
                stderr=subprocess.PIPE,
                timeout=120,
            )
        with index.open("rb") as incoming, (folder / "Packages.gz").open("wb") as outgoing:
            with gzip.GzipFile(fileobj=outgoing, mode="wb", mtime=0) as compressed:
                shutil.copyfileobj(incoming, compressed)
        signature = folder / "Packages.sig"
        run(
            [tool, "-S", "-m", str(index), "-s", str(private_key), "-x", str(signature)], stderr=subprocess.PIPE
        )
        run([tool, "-V", "-m", str(index), "-p", str(public_key), "-x", str(signature)], stderr=subprocess.PIPE)
        indexes = [index, folder / "Packages.gz", signature]
    else:
        index = folder / "packages.adb"
        packages = sorted(str(path) for path in folder.glob("*.apk"))
        run(
            [
                tool,
                "--keys-dir",
                str(keys),
                "mkndx",
                "--sign",
                str(private_key),
                "--output",
                str(index),
                *packages,
            ],
            stderr=subprocess.PIPE,
        )
        run(
            [tool, "--keys-dir", str(keys), "verify", str(index)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        indexes = [index]
    return indexes
