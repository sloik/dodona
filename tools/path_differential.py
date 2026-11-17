"""Compare the kernel's path check with the reference on many random paths.

Stage-0 helper (decision 0023).

    python tools/path_differential.py -- <kernel command>

Two implementations written independently, in different languages, from the
same document: the kernel's, and tools/pathcheck.py. This builds paths at
random from a pool of awkward pieces and requires the two to give the same
answer on every one. The seed is fixed, so a failure can be repeated.

The reference uses the Unicode tables of the Python that runs it and the
kernel uses the pinned version, so the pool holds only characters whose
properties are the same in both.
"""
from __future__ import annotations

import json
import pathlib
import random
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pathcheck  # noqa: E402

POOL = list("aAbZ09._- /\\:*") + [
    "é", "é", "ß", "ss", "K", "k", "ı", "i", "İ", "σ", "ς", "Σ",
    "CON", "nul", "com1", "LPT¹", "aux", "..", " ", "\t", "͸", "名", "ẞ", "ǆ", "ǅ",
    "ͅ", "\U0001F600", "ö", "ö", "ﬁ"]


def ask(command: list[str], sub: str, payload: dict) -> dict:
    done = subprocess.run(command + [sub], input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=30)
    return json.loads(done.stdout.decode("utf-8"))


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    rng = random.Random(20261117)
    singles = pairs = differences = 0
    for _ in range(1500):
        path = "".join(rng.choice(POOL) for _ in range(rng.randint(0, 7)))
        want = pathcheck.check(path.encode("utf-8"))
        answer = ask(command, "path", {"hex": path.encode("utf-8").hex()})
        got = None if answer.get("accepted") else answer.get("refused")
        singles += 1
        if got != want:
            differences += 1
            print(f"DIFFERENT {path!r}: reference {want}, kernel {got}")
    for _ in range(400):
        a = "".join(rng.choice(POOL[20:]) for _ in range(rng.randint(1, 4)))
        b = "".join(rng.choice(POOL[20:]) for _ in range(rng.randint(1, 4)))
        if a == b or pathcheck.check(a.encode("utf-8")) or pathcheck.check(b.encode("utf-8")):
            continue
        pairs += 1
        want = bool(pathcheck.collisions([a, b]))
        got = bool(ask(command, "path-set", {"paths": [a, b]})["collisions"])
        if got != want:
            differences += 1
            print(f"DIFFERENT pair {a!r} {b!r}: reference {want}, kernel {got}")
    print(json.dumps({"paths": singles, "pairs": pairs, "differences": differences, "all_agree": differences == 0}))
    return 0 if differences == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
