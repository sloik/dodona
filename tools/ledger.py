"""Read a ledger file as protocol/ledger.md defines it. The reference reader for the stage-0 helpers.

It only reads: appending is a kernel's (`ledger-append`). `read(path)` gives
`{"entries": [...], "torn": bool}`, or raises Corrupt with the line, counted from 1.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402

LINE = re.compile(rb"dodona1 (0|[1-9][0-9]*) ([0-9a-f]{64}) (.*)", re.S)


class Corrupt(Exception):
    def __init__(self, at: int):
        super().__init__(f"corrupt at line {at}")
        self.at = at


def read(path: pathlib.Path) -> dict:
    path = pathlib.Path(path)
    if not path.exists():
        return {"entries": [], "torn": False}
    data = path.read_bytes()
    complete, _, rest = data.rpartition(b"\n")
    torn = rest != b""
    if not complete and not data.endswith(b"\n"):
        lines = []
    else:
        lines = complete.split(b"\n") if data.count(b"\n") else []
    import host  # the strict reader of JSON as the canonical encoding writes it
    entries, previous = [], None
    for number, raw in enumerate(lines, 1):
        m = LINE.fullmatch(raw)
        if not m:
            raise Corrupt(number)
        payload = m.group(3)
        if len(payload) != int(m.group(1)) or hashlib.sha256(payload).hexdigest().encode("ascii") != m.group(2):
            raise Corrupt(number)
        try:
            entry = host.strict_load(payload)
        except Exception:  # noqa: BLE001 - any payload that is not strict JSON is corrupt
            raise Corrupt(number) from None
        if not isinstance(entry, dict) or set(entry) != {"previous", "kind", "body"} \
                or not isinstance(entry["kind"], str) or not entry["kind"] \
                or canonical.encode(entry).encode("utf-8") != payload or entry["previous"] != previous:
            raise Corrupt(number)
        entries.append({"kind": entry["kind"], "body": entry["body"]})
        previous = canonical.identity(entry)
    return {"entries": entries, "torn": torn}
