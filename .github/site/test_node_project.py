"""Exercise the Node provider through each native project command and its ledger.

    python3 .github/site/test_node_project.py --kernel FILE
"""
from __future__ import annotations

import argparse
import json
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile

SITE = pathlib.Path(__file__).resolve().parent
ROOT = SITE.parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import host  # noqa: E402

PROJECT = """[project]
name = "node-fixture"
config = "0.2"

[[binding]]
name = "tests"
provider = "dodona.node-test"
capabilities = ["obligation.enumerate", "obligation.check"]
match = ["*.test.js"]
"""
IMPORTS = """const test = require('node:test');
const { strictEqual } = require('node:assert');
"""
TESTS = {
    "good": "test('good', () => { strictEqual(2 + 2, 4); });",
    "bad": "test('bad', () => { strictEqual(2 + 2, 5); });",
    "skipped": "test('skipped', {skip: true}, () => {});",
}


def ask(command: list[str], request: dict) -> dict:
    done = subprocess.run(command, input=json.dumps(request).encode("utf-8"), capture_output=True, timeout=90, check=True)
    return json.loads(done.stdout)


def exercise(root: pathlib.Path, runner: list[str], readers: tuple[list[str], list[str]]) -> dict:
    (root / "dodona.toml").write_text(PROJECT, encoding="utf-8", newline="\n")
    for name, test in TESTS.items():
        (root / f"{name}.test.js").write_text(IMPORTS + test + "\n", encoding="utf-8", newline="\n")
    provider = "provider.py"
    shutil.copyfile(ROOT / "providers" / "node-test" / provider, root / provider)
    config = SITE / "local-executor.json"
    pin, = json.loads(config.read_text(encoding="utf-8"))["pins"]
    tool = {"name": pin["name"], "version": ">=" + pin["floor"], "digest": "sha256:" + host.floor_digest(pin)}
    os_name = {"darwin": "macos", "linux": "linux", "win32": "windows"}[sys.platform]
    arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower())
    named = {name: f"{name}.test.js::{name}" for name in TESTS}

    status_request = {
        "root": str(root), "project": "dodona.toml", "policy_source": "fixture", "owner_ledger": "owner.ledger",
        "ledgers": ["checks.ledger"],
        "policy": {"required": list(named.values()), "min_hard_gates": 0, "floors": {}, "not_applied": []},
        "site": {"writer": "node-fixture", "runner": "fixture", "platform": {"os": os_name, "arch": arch},
                 "tools": [tool], "deadline_ms": 20_000,
                 "providers": {"dodona.node-test": {"command": [sys.executable, provider], "code": [provider]}}},
    }
    run_request = dict(status_request, ledger="checks.ledger",
                       executor=[sys.executable, str(SITE / "local_executor.py"), str(config)])
    command = runner + ["run"]
    first = ask(command, run_request)
    assert first.get("counts") == {"obligations": 3, "reused": 0, "checked": 3, "refused": 0, "not_checkable": 0,
                                   "passed": 1, "failed": 1, "error": 1, "unavailable": 0, "unsupported": 0}, first
    ledger = root / "checks.ledger"
    read = ask(runner + ["ledger-read"], {"ledger": str(ledger)})
    expected = {named["good"]: "passed", named["bad"]: "failed"}
    assert len(read.get("entries", [])) == len(expected), read
    assert {e["body"]["obligation"]: e["body"]["verdict"] for e in read["entries"]} == expected, read
    for entry in read["entries"]:
        assert entry["kind"] == "evidence", entry
        assert entry["body"]["strength"] == {"class": "test", "rank": "sampled"}, entry
        assert entry["body"]["level"] == "sampled", entry

    statuses = dict(expected, **{named["skipped"]: "unknown"})
    for reader in readers:
        result = ask(reader + ["status"], status_request)
        observed = {name: item["status"] for name, item in result["report"]["obligations"].items()}
        assert observed == statuses, result

    original = ledger.read_bytes()
    second = ask(command, run_request)
    assert second.get("counts") == dict(first["counts"], reused=2, checked=1, passed=0, failed=0), second
    assert ledger.read_bytes() == original, "the skipped result changed the ledger"
    return {"first": first["counts"], "second": second["counts"], "statuses": statuses}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=pathlib.Path, required=True, help="the built Rust kernel")
    args = parser.parse_args()
    binary = args.kernel.resolve()
    if sys.platform == "win32" and not binary.suffix:
        binary = binary.with_suffix(".exe")
    runners = ([str(binary)], ["node", str(ROOT / "kernel2" / "dodona-kernel2.js")])
    results = []
    for runner in runners:
        with tempfile.TemporaryDirectory(prefix="dodona-node-project-") as tmp:
            results.append(exercise(pathlib.Path(tmp).resolve(), runner, runners))
    assert results[0] == results[1]
    print(json.dumps(results[0], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
