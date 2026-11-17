"""Reference implementation of the path check (protocol/path-check.md).

Stage-0 helper (decision 0023). It is judged by conformance/vectors/paths.json,
whose expected results were written by hand, and it is used to check this
repository's own paths.

Limitation: it uses the Unicode tables of the Python that runs it, not the
pinned version. For the repository's own paths and for the vectors this makes
no difference; a kernel must embed the pinned tables.
"""
from __future__ import annotations

import unicodedata

FORBIDDEN = set('\\:*?"<>|') | {chr(c) for c in range(0x20)} | {"\x7f"}
DEVICES = {"CON", "PRN", "AUX", "NUL"} | {f"{n}{d}" for n in ("COM", "LPT") for d in "0123456789\u00b9\u00b2\u00b3"}


def check(raw: bytes) -> str | None:
    """Return None if the path is accepted, otherwise the reason it is refused."""
    try:
        path = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return "not-utf8"
    if any(0xD800 <= ord(c) <= 0xDFFF for c in path):
        return "not-utf8"
    if not path:
        return "empty"
    if len(raw) > 200:
        return "too-long"
    segments = path.split("/")
    if any(s == "" for s in segments):
        return "empty-segment"
    if any(s in (".", "..") for s in segments):
        return "dot-segment"
    if any(len(s.encode("utf-8")) > 100 for s in segments):
        return "segment-too-long"
    if any(c in FORBIDDEN for c in path):
        return "forbidden-character"
    if any(s.endswith((".", " ")) for s in segments):
        return "trailing-dot-or-space"
    if any(s.startswith(" ") for s in segments):
        return "leading-space"
    if any(s.split(".", 1)[0].upper() in DEVICES for s in segments):
        return "reserved-name"
    if unicodedata.normalize("NFC", path) != path:
        return "not-nfc"
    if any(unicodedata.category(c) == "Cn" for c in path):
        return "unassigned-character"
    return None


def fold(path: str) -> str:
    """Canonical caseless form: NFD, full case folding, NFD."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", path).casefold())


def collisions(paths: list[str]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    found = []
    for path in sorted(paths):
        key = fold(path)
        if key in seen and seen[key] != path:
            found.append((seen[key], path))
        seen.setdefault(key, path)
    return found
