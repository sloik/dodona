"""A completed receipt for the focused, manual final-status proof lane.

    python .github/site/final_status_proof.py SYSTEM RECEIPT

SYSTEM is macos, linux or windows. RECEIPT is the output JSON path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = "4462d9bce3851027cfa7f37d2d1ceb49f0085a3e"
REF = "refs/heads/dodona-eight-40-final-status-proof"
SYSTEMS = {"macos": "darwin", "linux": "linux", "windows": "win32"}
KIT = ROOT / "conformance/project/cases.json"
CASE_COUNT = 253
RUST_TEST = "status::tests::final_report_applies_all_steps_and_constructs_one_report"
NODE_TESTS = (
    "a step with a value of the wrong type changes nothing",
    "status: an evidence entry with a wrongly typed field is not a record and is not rejected",
    "status: an obligation named __proto__ is kept as its own name in the report",
    "status project report uses the last result",
    "status project report materializes only once for generated history",
    "status project report falls back to scenario replay",
    "status final report replays key and gate transitions",
)
COUNTS = {"cases", "judged", "skipped", "matched", "all_matched"}


class Unfinished(ValueError):
    """The proof did not establish a complete agreement."""


def run(label: str, command: list[str], seconds: int) -> str:
    print(f"{label}: {subprocess.list2cmdline(command)}", flush=True)
    # A surviving grandchild can keep a pipe open on timeout. Redirect to files
    # so waiting for the invoked command does not also wait for inherited pipes.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err, timeout=seconds, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Unfinished(f"{label}: {error}") from error
        out.seek(0)
        err.seek(0)
        stdout = out.read().decode("utf-8", "backslashreplace")
        stderr = err.read().decode("utf-8", "backslashreplace")
    print(stdout, end="", flush=True)
    print(stderr, end="", file=sys.stderr, flush=True)
    if result.returncode != 0:
        raise Unfinished(f"{label}: native exit {result.returncode}")
    return stdout.replace("\r\n", "\n")


def invocation(system: str) -> dict:
    lane = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": "sloik/dodona",
            "GITHUB_REF": REF, "GITHUB_JOB": "final-status-proof"}
    if sys.platform != SYSTEMS[system] or any(os.environ.get(key) != value for key, value in lane.items()):
        raise Unfinished("wrong system or manual proof lane")
    head = run("Proof revision", ["git", "rev-parse", "HEAD"], 10).strip()
    if (not re.fullmatch(r"[0-9a-f]{40}", head)
            or head != os.environ.get("GITHUB_SHA") or head != os.environ.get("GITHUB_WORKFLOW_SHA")):
        raise Unfinished("checkout and dispatched workflow revisions differ")
    if run("Clean checkout", ["git", "status", "--porcelain"], 10).strip():
        raise Unfinished("proof checkout has local changes")
    run("Composed inputs", ["git", "diff", "--exit-code", "--stat", SOURCE, head, "--",
                            "kernel", "kernel2", "conformance", "tools", "spec/kernel", "spec/intent"], 20)
    run_id, attempt = (os.environ.get(key, "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"))
    if any(not re.fullmatch(r"[1-9][0-9]*", value) for value in (run_id, attempt)):
        raise Unfinished("missing run or attempt metadata")
    return {"source": SOURCE, "head": head, "system": system, "run_id": int(run_id), "attempt": int(attempt)}


def rust_result(log: str) -> None:
    if (log.splitlines().count(f"test {RUST_TEST} ... ok") != 1
            or log.splitlines().count("running 1 test") != 1
            or not re.search(r"^test result: ok\. 1 passed; 0 failed; 0 ignored;", log, re.MULTILINE)):
        raise Unfinished("Rust did not report the one exact passing test")


def node_result(log: str) -> None:
    tests = re.findall(r"^ok \d+ - ([^\r\n]+)$", log, re.MULTILINE)
    passed = [name for name in tests if not re.search(r"\s+#\s+(SKIP|TODO)\b", name, re.IGNORECASE)]
    if sorted(passed) != sorted(NODE_TESTS) or log.splitlines().count("# fail 0") != 1:
        raise Unfinished("Node did not report every named passing test")


def windows_skip(case: dict, reason: str) -> bool:
    ledgers = case.get("ledgers", [])
    owner = case.get("owner_ledger") or {}
    if reason == "this system cannot make a symbolic link":
        return bool(case.get("links") or case.get("outside_links") or owner.get("link") or owner.get("folder_link")
                    or any(item.keys() & {"dangling", "link_to", "link_to_owner"} for item in ledgers))
    if reason == "this system cannot make a hard link":
        return any(item.get("hardlink_to_owner") for item in ledgers)
    if reason == "this system cannot make a folder its own user cannot enter":
        return any("mode" in link for link in case.get("outside_links", {}).values())
    if reason == "this system cannot make a file or folder its own user cannot read":
        return bool(case.get("unreadable_mode"))
    return reason == "this system cannot make a folder or file its own user cannot read" and bool(case.get("unreadable"))


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise Unfinished("duplicate status footer field")
    return obj


def status_result(log: str, cases: list[dict], system: str) -> dict:
    lines = log.splitlines()
    names = [case["name"] for case in cases]
    if len(names) != CASE_COUNT or len(set(names)) != CASE_COUNT or len(lines) != CASE_COUNT + 1:
        raise Unfinished("status kit did not report the complete named case inventory")
    skipped = []
    for line, case in zip(lines[:-1], cases, strict=True):
        name = case["name"]
        if line == f"match    {name}":
            continue
        prefix = f"skipped  {name}: "
        if system == "windows" and line.startswith(prefix) and windows_skip(case, line[len(prefix):]):
            skipped.append({"name": name, "reason": line[len(prefix):]})
            continue
        raise Unfinished(f"status kit did not match or explicitly port-skip {name!r}")
    try:
        footer = json.loads(lines[-1], object_pairs_hook=unique_object)
    except ValueError as error:
        raise Unfinished(f"status kit has no usable final footer: {error}") from error
    if (not isinstance(footer, dict) or footer.keys() != COUNTS or footer["all_matched"] is not True
            or any(type(footer[key]) is not int for key in COUNTS - {"all_matched"})
            or footer["cases"] != CASE_COUNT or footer["skipped"] != len(skipped)
            or not 0 < footer["matched"] == footer["judged"] == CASE_COUNT - len(skipped)):
        raise Unfinished("status footer is incomplete or inconsistent")
    return dict(footer, skipped_cases=skipped)


def prove(system: str) -> dict:
    receipt = invocation(system)
    kit_bytes = KIT.read_bytes()
    cases = json.loads(kit_bytes)["cases"]
    manifest = ["--locked", "--manifest-path", "kernel/Cargo.toml"]
    output = run("Exact Rust final-report test", ["cargo", "test", *manifest, RUST_TEST, "--", "--exact"], 480)
    rust_result(output)
    pattern = "^(" + "|".join(re.escape(name) for name in NODE_TESTS) + ")$"
    output = run("Focused JavaScript final-report controls",
                 ["node", "--test", "--test-reporter=tap", f"--test-name-pattern={pattern}", "kernel2/test.js"], 60)
    node_result(output)
    run("Release kernel for the cross-kernel status kit", ["cargo", "build", "--release", *manifest], 600)
    rust_kernel = "kernel/target/release/dodona-kernel" + (".exe" if system == "windows" else "")
    rust = [rust_kernel]
    node = ["node", "kernel2/dodona-kernel2.js"]
    judge = [sys.executable, "tools/run_status_cases.py", "--jobs", "2", "--kernel"]
    statuses = {}
    failures = []
    commands = {"rust": [*judge, *node, "--", *rust, "status"],
                "javascript": [*judge, *rust, "--", *node, "status"]}
    for name, command in commands.items():
        try:
            statuses[name] = status_result(run(f"{name} status", command, 360), cases, system)
        except Unfinished as error:
            failures.append(str(error))
    if failures:
        raise Unfinished(" | ".join(failures))
    if statuses["rust"]["skipped_cases"] != statuses["javascript"]["skipped_cases"]:
        raise Unfinished("the two status commands did not judge the same cases on this system")
    statuses["suite_sha256"] = hashlib.sha256(kit_bytes).hexdigest()
    return dict(receipt, status="completed", rust_test=RUST_TEST, node_tests=NODE_TESTS, status_kit=statuses,
                rust_binary_sha256=hashlib.sha256((ROOT / rust_kernel).read_bytes()).hexdigest())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("system", choices=SYSTEMS)
    parser.add_argument("receipt", type=pathlib.Path)
    args = parser.parse_args()
    try:
        receipt = prove(args.system)
        line = json.dumps(receipt, sort_keys=True)
        with args.receipt.open("x", encoding="utf-8") as out:
            out.write(line + "\n")
    except (OSError, Unfinished) as error:
        print(json.dumps({"status": "unfinished", "system": args.system, "reason": str(error)}))
        return 2
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
