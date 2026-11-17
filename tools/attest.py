"""Vouch for the facts of an act record with a keyed check value. Stage-0 reference (decision 0027).

    python tools/attest.py sign   --key-file FILE --key-name NAME --covers FIELD,FIELD... < record.json
    python tools/attest.py verify --key-file FILE < record.json

This is the part of a harness that signs, and only that part. It does not
start a checker, hand it a brief or watch what it was given, so it cannot
know whether the facts it signs are true. Signing a record because the
working agent asked for it would make every claim look attested.

For that reason nothing here is used on dodona's own records. A harness that
is worth a higher grade must hold a key the working agent cannot read, start
the checker itself, and sign only what it observed. None exists yet.

The check value is HMAC-SHA256 under the key, over the canonical encoding of
{"covers": C, "fields": F}: C is the sorted list of covered field names and F
holds each of those fields of the record under its name.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402


def check_value(record: dict, covers: list[str], key: bytes) -> str:
    covered = {"covers": covers, "fields": {name: record[name] for name in covers}}
    return hmac.new(key, canonical.encode(covered).encode("utf-8"), hashlib.sha256).hexdigest()


def sign(record: dict, covers: list[str], key: bytes, key_name: str) -> dict:
    covers = canonical.sort_set(covers)
    missing = [name for name in covers if name not in record]
    if missing:
        raise ValueError(f"the record has no field {missing[0]}")
    signed = {k: v for k, v in record.items() if k != "attestation"}
    signed["attestation"] = {"harness": key_name, "key": key_name, "covers": covers, "mac": check_value(signed, covers, key)}
    return signed


def verify(record: dict, key: bytes) -> bool:
    given = record.get("attestation")
    if not isinstance(given, dict) or any(name not in record for name in given.get("covers", [])):
        return False
    return hmac.compare_digest(check_value(record, given["covers"], key), str(given.get("mac", "")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["sign", "verify"])
    ap.add_argument("--key-file", type=pathlib.Path, required=True, help="a file holding the key in hexadecimal")
    ap.add_argument("--key-name")
    ap.add_argument("--covers", default="")
    args = ap.parse_args()
    key = bytes.fromhex(args.key_file.read_text(encoding="ascii").strip())
    record = json.load(sys.stdin)
    if args.command == "verify":
        ok = verify(record, key)
        print(json.dumps({"verified": ok}))
        return 0 if ok else 1
    if not args.key_name or not args.covers:
        ap.error("sign needs --key-name and --covers")
    print(json.dumps(sign(record, args.covers.split(","), key, args.key_name)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
