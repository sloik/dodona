"""One hosted project status replay for issue 3, from an identified main artifact.

    python .github/site/replay_retained_status.py --check-checkout
    python .github/site/replay_retained_status.py RETAINED RECEIPT
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import host  # noqa: E402
from run_status_cases import OUT_KEYS, same  # noqa: E402

REPOSITORY = "sloik/dodona"
STATUS_SOURCE = "3da9675066aa15fa8ac2ee11817d675d2be2007d"
POLICY_COMMIT = "f43ae21f53f7d3a84e2315e6dcd6fc458dbc5ba2"
POLICY_SHA256 = "6be5e567e42bd590ac54f6790cea04e4b533d4cd1149571365fc3957cb60a9f6"
SOURCE_RUN = 44626497885
SOURCE_COMMIT = "c8396c4ffb5a4d65be3fa9bb3ac552905d287fcc"
ARTIFACT_ID = 14582487546
ZIP_SHA256 = "504d7673867ade1be4ad1d5c1483bb7167e030b15a6706df2bf0e4f0a0bbf82e"
MEMBER_DIGESTS = {
    "dodona.ledger": "6b5ce614e21ed2dcd27f18841a1dea297ada9d6cce61f8713695379f9f4d16eb",
    "status.json": "b2b586c89cd1b380769051a009b61739a36c8d7b2bf943dd1ad53d2b562bb9ba",
}
PROOF_FILES = (
    ".github/workflows/checks.yml",
    ".github/site/replay_retained_status.py",
    ".github/site/test_replay_retained_status.py",
)
INTENTS = {f"{number:04}" for number in range(1, 7)}
LEDGER_PATH = ".retained-status-proof/dodona.ledger"
OWNER_LEDGER = "records/owner.ledger"
RUST_BINARY = ROOT / "kernel/target/release/dodona-kernel"
JS_PROGRAM = "kernel2/dodona-kernel2.js"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def command(argv: list[str], data: bytes | None = None) -> bytes:
    return subprocess.run(argv, input=data, cwd=ROOT, timeout=120, capture_output=True, check=True).stdout


def read_object(raw: bytes) -> dict:
    value = host.strict_load(raw, limit=None)
    require(isinstance(value, dict), "expected a JSON object")
    return value


def checkout(expected_head: str) -> str:
    head = command(["git", "rev-parse", "HEAD"]).decode().strip()
    require(head == expected_head, "checkout differs from dispatched commit")
    changed = command(["git", "diff", "--name-only", "-z", STATUS_SOURCE, head]).decode().split("\0")
    require(set(changed).issubset({"", *PROOF_FILES}), "checkout changes the pinned status source")
    require(not command(["git", "status", "--porcelain", "--untracked-files=all"]), "checkout is dirty")
    return command(["git", "rev-parse", "HEAD^{tree}"]).decode().strip()


def check_source(run: dict, artifact: dict) -> None:
    require(
        run.get("id") == SOURCE_RUN and run.get("status") == "completed"
        and run.get("conclusion") == "success" and run.get("head_branch") == "main"
        and run.get("event") in ("push", "workflow_dispatch") and run.get("head_sha") == SOURCE_COMMIT
        and run.get("path") == ".github/workflows/models.yml"
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("repository", {}).get("full_name") == REPOSITORY,
        "retained run is not the pinned successful main workflow",
    )
    source = artifact.get("workflow_run", {})
    require(
        artifact.get("id") == ARTIFACT_ID and artifact.get("name") == "dodona-on-dodona"
        and artifact.get("expired") is False and artifact.get("size_in_bytes") == 191_839
        and artifact.get("digest") == f"sha256:{ZIP_SHA256}" and source.get("id") == SOURCE_RUN
        and source.get("head_sha") == SOURCE_COMMIT and source.get("head_branch") == "main"
        and type(source.get("repository_id")) is int and source["repository_id"] == run["repository"].get("id")
        and source.get("head_repository_id") == source.get("repository_id"),
        "retained artifact metadata differs from the pinned archive",
    )


def retained_members(raw: bytes) -> dict[str, bytes]:
    require(digest(raw) == ZIP_SHA256, "retained archive digest differs")
    members = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name, expected in MEMBER_DIGESTS.items():
            matching = [member for member in archive.infolist() if member.filename == name]
            require(len(matching) == 1, f"retained archive needs one {name}")
            members[name] = archive.read(matching[0])
            require(digest(members[name]) == expected, f"retained {name} digest differs")
    return members


def policy_blob(data: bytes) -> bytes:
    require(digest(data) == POLICY_SHA256, "pinned policy digest differs")
    return data


def check_report(answer: dict, policy_source: str, recomputed: dict) -> None:
    require("refused" not in answer, f"native status refused: {answer.get('refused')}")
    require(set(answer) == OUT_KEYS, "native status response has the wrong fields")
    require(answer["policy_source"] == policy_source, "native status lost the pinned policy source")
    for field in ("judged", "report"):
        intents = answer[field]["intents"]
        require(isinstance(intents, dict) and set(intents) == INTENTS, f"native {field} lacks the exact six intents")
    results = recomputed.get("results")
    require(isinstance(results, list) and bool(results), "second kernel returned no scenario results")
    require(same(answer["report"], results[-1]), "native report differs from the second kernel's scenario")
    report_status = answer["report"]["project"]["status"]
    expected = "unknown" if answer["project_doubts"] and report_status in ("passed", "nothing-required") else report_status
    require(answer["project_status"] == expected, "outer project status differs from the report and its doubts")


def check_ledger(answer: dict, ledger: bytes) -> None:
    require(ledger.endswith(b"\n"), "retained ledger has a torn ending")
    entries = [read_object(line.split(b" ", 3)[3]) for line in ledger.split(b"\n")[:-1]]
    steps = [{"do": {"append": {"kind": entry["kind"], "body": entry["body"]}}} for entry in entries]
    steps.append({"do": {"set_gate": {"intent": "", "criterion": "", "to": "hard"}}})
    require(same(answer["ledger"], {"entries": len(entries), "torn": False}), "native ledger receipt differs")
    require(same(answer["judged"]["steps"], steps), "native scenario did not keep the exact retained entries")


def status_input(policy: dict, policy_source: str) -> dict:
    tools, _ = host.lock_tools()
    providers = {}
    for name, directory, library in (
        ("dodona.tla", "tlc", "judge.py"),
        ("dodona.intent.markdown", "intents", "intents_md.py"),
    ):
        source = f"providers/{directory}/provider.py"
        providers[name] = {
            "command": [sys.executable, "-B", str(ROOT / source)],
            "code": [source, f"providers/{directory}/{library}"],
        }
    return {
        "root": str(ROOT), "project": "dodona.toml", "policy": policy, "policy_source": policy_source,
        "ledgers": [LEDGER_PATH], "owner_ledger": OWNER_LEDGER,
        "site": {"platform": host.PLATFORM, "writer": "ci", "runner": host.runner_code(),
                 "tools": tools, "providers": providers, "deadline_ms": 10_000},
    }


def replay(retained: Path, output: Path) -> None:
    head = os.environ["GITHUB_SHA"]
    tree = checkout(head)
    check_source(read_object((retained / "run.json").read_bytes()),
                 read_object((retained / "artifact.json").read_bytes()))
    members = retained_members((retained / "archive.zip").read_bytes())
    historical = read_object(members["status.json"])
    require(set(historical["intents"]) == INTENTS, "historical status does not cover the same six intents")

    pinned = retained / "policy.toml"
    pinned.write_bytes(policy_blob(command(["git", "show", f"{POLICY_COMMIT}:policy.toml"])))
    policy = read_object(command([sys.executable, "-B", "tools/policy_input.py", str(pinned)]))
    policy_source = f"{REPOSITORY}@{POLICY_COMMIT}:policy.toml sha256:{POLICY_SHA256}"
    request = status_input(policy, policy_source)
    request_bytes = encode(request)

    ledger = ROOT / LEDGER_PATH
    ledger.parent.mkdir()
    with ledger.open("xb") as destination:
        destination.write(members["dodona.ledger"])
    native_bytes = command([str(RUST_BINARY), "status"], request_bytes)
    answer = read_object(native_bytes)
    require("refused" not in answer, f"native status refused: {answer.get('refused')}")
    check_ledger(answer, members["dodona.ledger"])
    require(same(answer["policy_not_applied"], policy["not_applied"]), "native status did not preserve policy limitations")
    scenario_bytes = encode(answer["judged"])
    recomputed_bytes = command(["node", JS_PROGRAM, "scenario"], scenario_bytes)
    check_report(answer, policy_source, read_object(recomputed_bytes))
    require(digest(ledger.read_bytes()) == MEMBER_DIGESTS["dodona.ledger"], "native status changed the retained ledger")

    summary = {
        "head": head, "tree": tree, "status_source": STATUS_SOURCE,
        "proof_run": os.environ["GITHUB_RUN_ID"], "proof_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "source": {"run": SOURCE_RUN, "head": SOURCE_COMMIT, "artifact": ARTIFACT_ID,
                   "zip_sha256": ZIP_SHA256, "member_sha256": MEMBER_DIGESTS},
        "policy": {"commit": POLICY_COMMIT, "sha256": POLICY_SHA256, "source": answer["policy_source"]},
        "site": {key: value for key, value in request["site"].items() if key != "providers"},
        "host": {"os": platform.system(), "machine": platform.machine(), "python": platform.python_version(),
                 "node": command(["node", "--version"]).decode().strip(),
                 "rustc": command(["rustc", "--version"]).decode().strip()},
        "sha256": {"request": digest(request_bytes), "native_status": digest(native_bytes),
                   "scenario_input": digest(scenario_bytes), "scenario_result": digest(recomputed_bytes),
                   "rust_binary": digest(RUST_BINARY.read_bytes())},
        "intents": answer["report"]["intents"],
        "obligation_statuses": Counter(item["status"] for item in answer["report"]["obligations"].values()),
        "project": answer["report"]["project"], "project_status": answer["project_status"],
        "project_doubts": answer["project_doubts"], "policy_not_applied": answer["policy_not_applied"],
        "ledger": answer["ledger"], "scenario_agrees": True,
    }
    output.mkdir()
    (output / "request.json").write_bytes(request_bytes)
    (output / "native-status.json").write_bytes(native_bytes)
    (output / "summary.json").write_bytes(encode(summary) + b"\n")
    (output / "complete.txt").write_text("native status replay completed and scenario report agreed\n", encoding="utf-8")
    print(encode(summary).decode())
    print("native status replay completed and scenario report agreed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check-checkout", action="store_true")
    parser.add_argument("retained", type=Path, nargs="?")
    parser.add_argument("receipt", type=Path, nargs="?")
    args = parser.parse_args()
    try:
        if args.check_checkout and args.retained is None and args.receipt is None:
            print(checkout(os.environ["GITHUB_SHA"]))
        elif not args.check_checkout and args.retained is not None and args.receipt is not None:
            replay(args.retained, args.receipt)
        else:
            parser.error("give --check-checkout or both RETAINED and RECEIPT")
    except (ValueError, OSError, KeyError, IndexError, TypeError, zipfile.BadZipFile, host.Refused, subprocess.SubprocessError) as error:
        raise SystemExit(f"retained status replay stopped: {error}") from None
