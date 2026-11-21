"""Judge how strictly a kernel reads its input. Stage-0 helper (decision 0023).

    python tools/run_input_cases.py -- <kernel command>

A kernel must read every input as strictly as the canonical encoding writes
(conformance/README.md). Otherwise a record could be signed with one value and
read with another: `"result": "refused", "result": "agreed"`, or `1` signed and
`1.0` read. Each case here is a valid input with one such fault written into
its text, sent to each command that takes JSON; the kernel must exit with a
status other than 0. A control, the same input without the fault, must be
answered. The inputs are taken from the kit itself.

Any status other than 0 that the kernel returned on its own counts as a
refusal, a crash it reports as an ordinary status included (a panic's 101, a
shell's 128 + N). A kernel that could not be started, ran out of time or was
ended by the operating system has answered nothing, and that case is
`UNFINISHED`: a negative status (a POSIX signal), or a status in the NTSTATUS
error range 0xC0000000 to 0xCFFFFFFF, which is how Windows reports a process
ended by an exception such as an access violation. Other ways a process can
be ended from outside, such as a Windows kill that sets an ordinary status,
cannot be told apart and still count as a refusal. A child that exits nonzero
with a disk-full diagnostic on standard error leaves the case unfinished. A case answered wrongly is
`MISMATCH`, named in `rejected`. Exit status is 0 if every case matched, 1 if
the run completed with mismatches, and 2 if any case or the judge itself did
not finish, after mismatches too, or no case ran.
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


def ended_by_the_system(code: int) -> bool:
    """A status the kernel did not return itself: a POSIX signal, or a Windows exception (NTSTATUS error range)."""
    return code < 0 or 0xC0000000 <= code <= 0xCFFFFFFF


def run(command: list[str], data: bytes) -> tuple[int | None, str]:
    """The kernel's own exit status, or None and why when it gave none."""
    try:
        result = subprocess.run(command + ["scenario"], input=data, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as err:
        return None, f"{type(err).__name__}: {err}"
    code = result.returncode
    if code != 0 and (b"No space left on device" in result.stderr or b"ENOSPC" in result.stderr):
        return None, "disk full"
    if ended_by_the_system(code):
        return None, f"ended by the system (exit {code})"
    return code, ""


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    cases: list[tuple[str, bytes, bool]] = []
    rejected: list[str] = []
    unfinished = 0
    try:
        source = json.loads((ROOT / "conformance" / "kernel" / "status" / "nothing_confirmed_is_a_draft.json").read_text(encoding="utf-8"))
        asked = {"kind": source["kind"], **{k: v for k, v in source.items() if k not in ("kind", "claim", "covers", "why", "steps")},
                 "steps": [{"do": step["do"]} for step in source["steps"]]}
        text = json.dumps(asked)
        assert '"min_hard_gates": 1' in text
        cases.append(("the input without a fault is answered", text.encode("utf-8"), True))
        cases += [(f"{name} is refused", faulty.encode("utf-8", errors="surrogateescape"), False) for name, faulty in faults(text)]
    except Exception as err:  # the judge could not build its cases: nothing was judged, which is not a pass or a mismatch
        unfinished = 1
        print(f"UNFINISHED the cases could not be made: {type(err).__name__}: {err}")
    for name, data, answered in cases:
        code, why = run(command, data)
        if code is None:
            unfinished += 1
            print(f"UNFINISHED {name}: {why}")
        elif (code == 0) == answered:
            print(f"match    {name} (exit {code})")
        else:
            rejected.append(name)
            print(f"MISMATCH {name} (exit {code})")
    matched = len(cases) - len(rejected) - unfinished if cases else 0
    print(json.dumps({"cases": len(cases), "matched": matched,
                      "all_matched": not rejected and not unfinished and bool(cases),
                      "unfinished": unfinished, "rejected": rejected}))
    if unfinished or not cases:
        return 2
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
