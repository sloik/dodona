"""Reference implementation of the canonical encoding (protocol/canonical-encoding.md).

Stage-0 helper (decision 0023). It is judged by conformance/vectors/canonical.json
and is used to produce expected values for other vectors, so that those do not
come from any kernel.
"""
from __future__ import annotations

import hashlib
import json

LIMIT = 9007199254740991


def encode(value) -> str:
    """The canonical text of a value built from dict, list, str, int, bool and None."""
    if isinstance(value, dict):
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + encode(value[k]) for k in keys) + "}"
    if isinstance(value, list):
        return "[" + ",".join(encode(v) for v in value) + "]"
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        if not -LIMIT <= value <= LIMIT:
            raise ValueError("integer-out-of-range")
        return str(value)
    raise ValueError("not-an-integer")


def identity(value) -> str:
    return "sha256:" + hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def sort_set(items: list[str]) -> list[str]:
    return sorted(set(items), key=lambda k: k.encode("utf-16-be"))
