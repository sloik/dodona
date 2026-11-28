"""Generate a draft lock from exact, staged single-file releases (decision 0008).

    python tools/resolve_staged_lock.py RELEASES.json LOCK.json
    python tools/resolve_staged_lock.py --preserve PREVIOUS.json RELEASES.json LOCK.json

Release directories are relative to RELEASES.json. The caller supplies the
publisher's SHA-256 for each release. The helper runs offline and opens
release files as data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host  # noqa: E402
import pathcheck  # noqa: E402
import tooltree  # noqa: E402


PLATFORM = {
    "os": ("linux", "macos", "windows"),
    "arch": ("aarch64", "x86_64"),
    "libc": ("gnu", "musl"),
    "emulated_on": ("aarch64", "x86_64"),
}


def has_fields(value, *fields: str) -> bool:
    return isinstance(value, dict) and value.keys() == set(fields)


def platform_key(platform) -> tuple[str, ...]:
    if (not isinstance(platform, dict) or not {"os", "arch"} <= platform.keys()
            or any(field not in PLATFORM or value not in PLATFORM[field] for field, value in platform.items())):
        raise host.Refused("bad-source: expected an exact platform")
    if platform.get("emulated_on") == platform["arch"]:
        raise host.Refused("bad-source: emulated_on must name a different architecture")
    return tuple(platform.get(field, "") for field in PLATFORM)


def portable_path(value) -> bool:
    return isinstance(value, str) and pathcheck.check(value.encode("utf-8")) is None


def release_source(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        address = urlsplit(value)
        return address.scheme == "https" and bool(address.hostname and address.path) and address.username is None
    except ValueError:
        return False


def is_reparse_point(details: os.stat_result) -> bool:
    return bool(getattr(details, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def same_file(first: Path, second: Path) -> bool:
    """Compare existing filesystem objects, allowing a new output path."""
    try:
        return first.samefile(second)
    except FileNotFoundError:
        return False


def measured_pin(root: Path, pin, destination: Path) -> dict:
    if not has_fields(pin, "platform", "tree", "entry", "upstream"):
        raise host.Refused("bad-source: expected a staged platform pin")
    platform_key(pin["platform"])
    tree, entry, upstream = pin["tree"], pin["entry"], pin["upstream"]
    if not portable_path(tree) or not portable_path(entry) or "/" in entry:
        raise host.Refused("bad-source: expected a relative tree and a single file name")
    if not has_fields(upstream, "source", "published_digest") or not release_source(upstream["source"]):
        raise host.Refused("bad-source: expected an HTTPS release and its published digest")
    expected = upstream["published_digest"]
    if not isinstance(expected, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", expected):
        raise host.Refused("bad-source: expected a published SHA-256 identity")

    directory = root
    for part in tree.split("/"):
        directory /= part
        details = directory.lstat()
        if not stat.S_ISDIR(details.st_mode) or is_reparse_point(details):
            raise host.Refused(f"not-a-plain-directory: {tree}")
    if any(same_file(directory, path) for path in (destination, *destination.parents)):
        raise host.Refused(f"output-in-staged-tree: {tree}")
    if [item.name for item in directory.iterdir()] != [entry]:
        raise host.Refused(f"unexpected-tree-contents: {tree}")
    artifact = directory / entry
    details = artifact.lstat()
    mode = details.st_mode
    if not stat.S_ISREG(mode) or is_reparse_point(details) or (os.name != "nt" and not mode & stat.S_IXUSR):
        raise host.Refused(f"not-a-program: {tree}/{entry}")
    with artifact.open("rb") as content:
        actual = "sha256:" + hashlib.file_digest(content, "sha256").hexdigest()
    if actual != expected:
        raise host.Refused(f"published-digest-mismatch: {tree}/{entry}")
    digest = tooltree.digest([{"path": entry, "kind": "program", "identity": actual}])
    return {"platform": pin["platform"], "digest": digest, "entry": entry, "upstream": upstream}


def requirements_of(name: str, entries: dict, direct: dict) -> list[str]:
    seen = set()
    pending = list(direct[name])
    while pending:
        requirement = pending.pop()
        if requirement == name:
            raise host.Refused(f"cyclic-requirement: {name}")
        if requirement in seen:
            continue
        if requirement not in entries or entries[requirement]["kind"] != "tool":
            raise host.Refused(f"missing-requirement: {name} requires tool {requirement!r}")
        seen.add(requirement)
        pending.extend(direct[requirement])
    return sorted(seen, key=lambda key: key.encode("utf-8"))


def resolve(source, root: Path, destination: Path) -> dict:
    if not has_fields(source, "entries") or not isinstance(source["entries"], list):
        raise host.Refused("bad-source: expected a list of release entries")
    entries = {}
    direct = {}
    platforms = {}
    for record in source["entries"]:
        if not has_fields(record, "kind", "name", "version", "requires", "platforms"):
            raise host.Refused("bad-source: expected kind, name, version, requires and platforms")
        kind, name, version = record["kind"], record["name"], record["version"]
        required, declared = record["requires"], record["platforms"]
        if (kind not in ("provider", "tool") or not isinstance(name, str) or not name
                or not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version)
                or not isinstance(required, list) or not all(isinstance(item, str) and item for item in required)
                or not isinstance(declared, list) or not declared):
            raise host.Refused("bad-source: invalid release entry")
        if name in entries or len(set(required)) != len(required):
            raise host.Refused(f"bad-source: repeated name or direct requirement for {name!r}")
        coverage = {}
        for pin in declared:
            measured = measured_pin(root, pin, destination)
            platform = platform_key(measured["platform"])
            if platform in coverage:
                raise host.Refused(f"duplicate-platform: {name!r} {measured['platform']}")
            coverage[platform] = measured
        entries[name] = {"kind": kind, "name": name, "version": version,
                         "platforms": [coverage[key] for key in sorted(coverage)]}
        direct[name] = required
        platforms[name] = coverage.keys()

    order = sorted(entries, key=lambda name: (entries[name]["kind"], name.encode("utf-8")))
    for name in order:
        needed = requirements_of(name, entries, direct)
        for requirement in needed:
            if not platforms[name] <= platforms[requirement]:
                raise host.Refused(f"missing-platform: {requirement!r} cannot serve every platform of {name!r}")
        entries[name]["requires"] = [{"name": required, "version": entries[required]["version"]} for required in needed]
    return {"lock": "0.2", "entries": [entries[name] for name in order]}


def preserve_platforms(previous, candidate: dict) -> None:
    """Require every entry and exact platform pin of the staged predecessor."""
    if not has_fields(previous, "lock", "entries") or previous["lock"] != "0.2" or not isinstance(previous["entries"], list):
        raise host.Refused("bad-baseline: expected a generated staged lock")
    by_name = {(entry["kind"], entry["name"]): entry for entry in candidate["entries"]}
    old_entries = set()
    for entry in previous["entries"]:
        if (not has_fields(entry, "kind", "name", "version", "requires", "platforms")
                or entry["kind"] not in ("provider", "tool") or not isinstance(entry["name"], str)
                or not isinstance(entry["platforms"], list) or not entry["platforms"]):
            raise host.Refused("bad-baseline: expected an exact lock entry")
        name = (entry["kind"], entry["name"])
        if name in old_entries:
            raise host.Refused("bad-baseline: repeated lock entry")
        old_entries.add(name)
        replacement = by_name.get(name)
        if replacement is None or any(entry[field] != replacement[field] for field in ("version", "requires")):
            raise host.Refused(f"previous-entry-changed: {entry['name']}")
        old_platforms = set()
        for pin in entry["platforms"]:
            if pin not in replacement["platforms"]:
                raise host.Refused(f"previous-pin-changed: {entry['name']}")
            platform = platform_key(pin["platform"])
            if platform in old_platforms:
                raise host.Refused("bad-baseline: repeated platform")
            old_platforms.add(platform)


def publish(destination: Path, lock: dict) -> None:
    encoded = (json.dumps(lock, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as output:
            temporary = Path(output.name)
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preserve", type=Path, help="a previously generated lock whose entries this extension retains")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    asked = parser.parse_args()
    try:
        source = asked.source.resolve(strict=True)
        destination = asked.output.resolve()
        if same_file(source, destination):
            raise host.Refused("output-is-source")
        lock = resolve(host.strict_load(source.read_bytes()), source.parent, destination)
        if asked.preserve is not None:
            predecessor = asked.preserve.resolve(strict=True)
            if same_file(predecessor, destination):
                raise host.Refused("output-is-preserved-lock")
            preserve_platforms(host.strict_load(predecessor.read_bytes()), lock)
        publish(asked.output, lock)
    except (host.Refused, tooltree.Unusable, OSError, ValueError, RuntimeError) as err:
        print(f"refused: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
