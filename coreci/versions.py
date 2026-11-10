if __package__:
    from .contract import SEMVER, require
else:
    from contract import SEMVER, require


def versions(tag, revision, package_format, target=None):
    match = SEMVER.fullmatch(tag)
    require(match is not None and type(revision) is int and 0 < revision < 2**64, "invalid source/rebuild version")
    require(package_format in ("deb", "rpm", "ipk", "apk"), "unsupported package format")
    upstream = ".".join(match.group(index) for index in (1, 2, 3))
    tokens = []
    if match.group(4):
        for identifier in match.group(4).split("."):
            if identifier.isdigit():
                require(identifier == "0" or not identifier.startswith("0"), "leading zero in prerelease identifier")
                tokens.extend([1, len(identifier), *map(int, identifier)])
            else:
                tokens.extend([2, *map(ord, identifier), 0])
        tokens.append(0)
        if package_format == "apk":
            upstream += "_pre0" + "".join("_p" + str(token) for token in tokens)
        else:
            upstream += "~" + ".".join("p" + str(token) for token in tokens)
    release = str(revision) if package_format in ("deb", "rpm") else "r" + str(revision)
    if package_format == "deb" and target is not None:
        release += "~" + target["suite"]
    elif package_format == "rpm" and target is not None:
        release += "." + {"fedora": "fc", "rocky": "el"}[target["distribution"]] + target["suite"]
    require(len(upstream + "-" + release) <= 240, "encoded package version exceeds supported length")
    result = {"version": upstream, "release": release, "full": upstream + "-" + release}
    return result
