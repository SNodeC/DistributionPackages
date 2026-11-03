"""Apply only the controller's committed, exact feed removals; reuse publisher indexes."""

import re

from contract import SHA256, file_hash, regular_file, relative_path, require
from sign_native import apt_indexes, feed_component, rpm_indexes, signing_key


def update(selected, feed, private_key, passphrase, public_key, temporary_root, tools):
    target = selected["target"]
    distribution, suite, arch = (feed_component(target[key]) for key in ("distribution", "suite", "arch"))
    package_format = target["build"]["format"]
    folder, suffix = {
        "deb": (distribution + "/pool/" + suite, "_" + arch + ".deb"),
        "rpm": (distribution + "/" + suite + "/" + arch + "/Packages", "." + arch + ".rpm"),
        "ipk": ("openwrt/" + suite + "/" + arch, "_" + arch + ".ipk"),
        "apk": ("openwrt/" + suite + "/" + arch, ".apk"),
    }[package_format]
    removed, packages = [], False
    for item in selected["objects"]:
        name = item["path"]
        path = relative_path(name)
        metadata = re.fullmatch(r"(?:receipts/[a-f0-9]{64}/[1-9][0-9]{0,19}\.json|exports/[a-f0-9]{64}/[1-9][0-9]{0,19}/development\.tar\.gz)", name)
        require((str(path.parent) == folder and path.name.endswith(suffix)) or metadata, "removal outside assigned target")
        require(name not in removed and all(not (feed / parent).is_symlink() for parent in path.parents), "duplicate or linked removal")
        file = regular_file(feed, name)
        require(type(item["size"]) is int and item["size"] > 0 and SHA256.fullmatch(item["sha256"])
                and file.stat().st_size == item["size"] and file_hash(file) == item["sha256"], "removal bytes differ from authority")
        packages = packages or metadata is None
        removed.append(name)
    # All exact bytes and paths are checked before any local deletion. Nothing remote is changed here.
    for name in removed:
        (feed / name).unlink()
    indexes = []
    if packages:
        if package_format in ("deb", "rpm"):
            with signing_key(private_key, passphrase, public_key, selected["source"]["deployment"]["signing"]["gpg_fingerprint"],
                             temporary_root) as (_, gpg, keyring):
                indexes = (apt_indexes if package_format == "deb" else rpm_indexes)(feed, distribution, suite, arch, gpg, keyring)
        else:
            from sign_openwrt import indexes as openwrt_indexes, signing_tools

            with signing_tools(selected, feed, private_key, public_key, temporary_root, tools, selected["environment"]) as (sdk, tool, keys, root):
                indexes = openwrt_indexes(root, package_format, sdk, tool, keys, private_key, public_key)
    paths = removed + [str(path.relative_to(feed)) for path in indexes]
    return paths, removed
