"""Judge how strictly a kernel reads its input. Stage-0 helper (decision 0023).

    python tools/run_input_cases.py -- <kernel command>

A kernel must read every input as strictly as the canonical encoding writes
(conformance/README.md). Otherwise a record could be signed with one value and
read with another: `"result": "refused", "result": "agreed"`, or `1` signed and
`1.0` read. Each case here is a valid input with one such fault written into
its text, sent to each command that takes JSON; the kernel must exit with a
status other than 0. A control, the same input without the fault, must be
answered. The inputs are taken from the kit itself.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def faults(text: str) -> list[tuple[str, str]]:
    """The same JSON text with one fault each. `text` is compact JSON whose first key is "kind"."""
    assert text.startswith('{"kind": ')
    return [("a key repeated in one object", '{"kind": "nothing", ' + text[1:]),
            ("a number written with a fraction", text.replace('"min_hard_gates": 1', '"min_hard_gates": 1.0', 1)),
            ("a number written with an exponent", text.replace('"min_hard_gates": 1', '"min_hard_gates": 1e0', 1)),
            ("a number too precise to be an integer", text.replace('"min_hard_gates": 1', '"min_hard_gates": 1.00000000000000001', 1)),
            ("a byte that is not UTF-8", text[:-1] + ', "x": "\udcff"}')]


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    source = json.loads((ROOT / "conformance" / "kernel" / "status" / "nothing_confirmed_is_a_draft.json").read_text(encoding="utf-8"))
    asked = {"kind": source["kind"], **{k: v for k, v in source.items() if k not in ("kind", "claim", "covers", "why", "steps")},
             "steps": [{"do": step["do"]} for step in source["steps"]]}
    text = json.dumps(asked)
    assert '"min_hard_gates": 1' in text
    failed = 0

    def run(data: bytes) -> int:
        try:
            return subprocess.run(command + ["scenario"], input=data, capture_output=True, timeout=60).returncode
        except (OSError, subprocess.TimeoutExpired):
            return -1

    control = run(text.encode("utf-8"))
    print(f"{'match   ' if control == 0 else 'MISMATCH'} the input without a fault is answered (exit {control})")
    failed += control != 0
    for name, faulty in faults(text):
        data = faulty.encode("utf-8", errors="surrogateescape")
        code = run(data)
        ok = code not in (0, -1)
        failed += not ok
        print(f"{'match   ' if ok else 'MISMATCH'} {name} is refused (exit {code})")
    total = 1 + len(faults(text))
    print(json.dumps({"cases": total, "matched": total - failed, "all_matched": failed == 0}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
