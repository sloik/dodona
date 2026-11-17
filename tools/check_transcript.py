"""Validate every message of a recorded provider session against the protocol schemas.

Stage-0 helper (decision 0023). Needs the `jsonschema` package.

    python tools/check_transcript.py FILE...

A transcript is what tools/host.py saves: a list of {"to", "message"}.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        import jsonschema
        from referencing import Registry, Resource
    except ImportError:
        print("the jsonschema package is not installed; nothing was checked")
        return 2
    registry = Registry()
    for path in sorted((ROOT / "protocol").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        for name in {schema.get("$id", path.name), path.name}:
            registry = registry.with_resource(name, Resource.from_contents(schema))
    messages = json.loads((ROOT / "protocol" / "messages.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(messages, registry=registry)
    count = problems = 0
    for name in sys.argv[1:]:
        for number, item in enumerate(json.loads(pathlib.Path(name).read_text(encoding="utf-8")), start=1):
            count += 1
            error = jsonschema.exceptions.best_match(validator.iter_errors(item["message"]))
            if error is not None:
                problems += 1
                if problems <= 10:
                    where = "/".join(str(part) for part in error.absolute_path)
                    print(f"PROBLEM {name} message {number} (to the {item['to']}) at {where or 'the top'}: {error.message[:200]}")
    print(json.dumps({"messages": count, "problems": problems}))
    return 0 if count and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
