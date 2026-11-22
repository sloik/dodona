"""A reference harness: it starts a checker itself and signs what it did. Stage-0 reference (decision 0027).

    python tools/harness.py --key-file FILE --key-name NAME --ticket T --kind KIND --target ID
        --intent I [--criterion C] --worker-id W --worker-session S --brief-from kernel|owner
        --work FILE --criteria FILE --brief FILE [--known-wrong FILE --known-right FILE --known-from kernel|owner]
        [--checker-make VENDOR/FAMILY --worker-make VENDOR/FAMILY] -- <checker command>

What it does, and so what its check value means:

1. It makes a new, empty directory and puts in it only the material named on
   the command line. Nothing else of the worker's is there.
2. It starts the checker itself, in that directory, with an environment that
   holds almost nothing, once per piece of work: first the known-wrong and
   known-right cases if they were given, then the real work. The checker's
   last line of output must be `agreed` or `refused`.
3. It keeps everything the checker printed as the transcript.
4. It writes the act record from what it did and saw, and signs it.

What it does not do: confine the checker. The directory is new and holds
only the named material, and the environment is nearly empty, but the
checker runs as the same user and can read any file that user can read. A
checker told where the worker's notes are, or where the key is, can read
them. "fresh_context" in the record means the checker was started anew with
only that material handed to it, not that it could see nothing else. A
harness worth trusting runs the checker where the worker's files and the key
are not reachable at all: another machine, or a container with nothing
mounted.

What it takes on the caller's word, and cannot know: who the worker is, who
wrote the brief, who supplied the known cases, and which make of model the
checker and the worker are. A harness worth trusting gets those from
somewhere the working agent cannot write, such as the ticket a kernel issued.
And the key: this program reads it from a file, so whoever can read that file
can sign anything. It shows what a harness must do. Run by the working agent
on its own work it proves nothing, and it is not used on dodona's own records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import secrets
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import attest  # noqa: E402

# The fields the facts read, and the four that bind the value to what was judged.
COVERS = ["actor", "brief", "fresh_context", "given", "known_bad", "transcript", "worker", "kind", "target", "result", "lineage", "ticket"]


def identity(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def ask(checker: list[str], material: dict[str, bytes], log: list[bytes]) -> str:
    """Start the checker in a new directory holding only `material`; return its last line."""
    with tempfile.TemporaryDirectory(prefix="dodona-harness-") as room:
        for name, data in material.items():
            pathlib.Path(room, name).write_bytes(data)
        env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if k in os.environ}
        try:
            done = subprocess.run(checker, cwd=room, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
            said = done.stdout + done.stderr
        except (OSError, subprocess.TimeoutExpired) as err:
            said = f"the checker did not finish: {type(err).__name__}\n".encode("utf-8")
        log.append(b"--- " + ", ".join(sorted(material)).encode("utf-8") + b"\n" + said)
        lines = [line.strip() for line in said.decode("utf-8", "replace").splitlines() if line.strip()]
        return lines[-1] if lines and lines[-1] in ("agreed", "refused") else "refused"


def run(args, checker: list[str]) -> dict:
    read = lambda path: pathlib.Path(path).read_bytes()  # noqa: E731
    work, criteria, brief = read(args.work), read(args.criteria), read(args.brief)
    log: list[bytes] = []
    given = [{"role": "brief", "content": identity(brief)}, {"role": "criteria", "content": identity(criteria)}]
    known = None
    if args.known_wrong and args.known_right:
        wrong, right = read(args.known_wrong), read(args.known_right)
        known = {"wrong": identity(wrong), "right": identity(right), "supplied_by": args.known_from,
                 "rejected_wrong": ask(checker, {"work": wrong, "criteria": criteria, "brief": brief}, log) == "refused",
                 "accepted_right": ask(checker, {"work": right, "criteria": criteria, "brief": brief}, log) == "agreed"}
        if args.criterion:
            known["criterion"] = args.criterion
        given += [{"role": "known-right", "content": identity(right)}, {"role": "known-wrong", "content": identity(wrong)}]
    result = ask(checker, {"work": work, "criteria": criteria, "brief": brief}, log)
    given.append({"role": "work", "content": identity(work)})
    lineage = {"intent": args.intent, "kind": args.kind}
    if args.criterion:
        lineage["criterion"] = args.criterion
    actor = {"id": "checker-" + hashlib.sha256(json.dumps(checker).encode("utf-8")).hexdigest()[:12],
             "session": "s-" + secrets.token_hex(8), "started_by": args.key_name}
    worker = {"id": args.worker_id, "session": args.worker_session}
    for who, make in ((actor, args.checker_make), (worker, args.worker_make)):
        if make:
            vendor, _, family = make.partition("/")
            who["make"] = {"vendor": vendor, "family": family}
    record = {"ticket": args.ticket, "kind": args.kind, "target": args.target, "lineage": lineage, "result": result,
              "actor": actor, "worker": worker, "brief": {"issued_by": args.brief_from, "content": identity(brief)},
              "given": sorted(given, key=lambda item: (item["role"], item["content"])), "fresh_context": True,
              "transcript": identity(b"".join(log))}
    if known:
        record["known_bad"] = known
    key = bytes.fromhex(pathlib.Path(args.key_file).read_text(encoding="ascii").strip())
    return attest.sign(record, COVERS, key, args.key_name)


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    at = sys.argv.index("--")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("key-file", "key-name", "ticket", "kind", "target", "intent", "worker-id", "worker-session", "work", "criteria", "brief"):
        ap.add_argument("--" + name, required=True)
    ap.add_argument("--brief-from", choices=["kernel", "owner"], required=True)
    for name in ("criterion", "known-wrong", "known-right", "checker-make", "worker-make"):
        ap.add_argument("--" + name)
    ap.add_argument("--known-from", choices=["kernel", "owner"], default="owner")
    args = ap.parse_args(sys.argv[1:at])
    print(json.dumps(run(args, sys.argv[at + 1:])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
