"""Compare both native project status commands with the retained issue 3 receipt.

    python .github/site/replay_retained_status.py --check-checkout
    python .github/site/replay_retained_status.py RETAINED PRIOR RECEIPT
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import host  # noqa: E402
from run_status_cases import OUT_KEYS, same  # noqa: E402

REPOSITORY = "sloik/dodona"
STATUS_SOURCE = "4462d9bce3851027cfa7f37d2d1ceb49f0085a3e"
RECORDED_SOURCE = "ee24e67b2b830a8810403021e721fb5aede67798"
QUALIFICATION_HEAD = "a1dba84ea83b45f696fc2c2eea58a1ce31147b03"
RECORD_PATHS = {"README.md", "spec/CLAIMS.md", "spec/runs/index.json"} | {
    f"spec/runs/run-15/every-state/{name}.txt" for name in (
        "built-kernel.sha256", "complete", "evidence-first-kernel", "evidence-second-kernel",
        "head", "input-files.sha256", "intent-first-kernel", "intent-second-kernel",
        "provenance.json", "tool-versions",
    )
}
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
PRIOR_RUN = 44925244772
PRIOR_COMMIT = "e9ff9697ee6049e9533728dcdc8f492dc75c3216"
PRIOR_STATUS_SOURCE = "3da9675066aa15fa8ac2ee11817d675d2be2007d"
PRIOR_ID = 14716281818
PRIOR_ZIP_SHA256 = "679000c44b2b1520c945b9cecc587fd634cd95427843322246541eaaeab11b0e"
PRIOR_MEMBERS = {
    "complete.txt": "deb1e6c20a74df705d78c39cb66d9e4ba3a039dded50ef211631ca18253a6b30",
    "js-final-report.json": "5ae05a7b297197faa447189adf1423852cf3a20ce146de80c31b02d87131923a",
    "native-status.json": "74599cfc36313986cf521cc2fc7436164a0d61254f7188d10d64ed7159552383",
    "request.json": "f6f87704b6ac5bda34aa56725f603cd1637bb6b9b0cc33d1660b231f76365b42",
    "summary.json": "edfc2019ca4c67f47167c767043313224e0c87b1a410cedd20bf15f2bce9fe37",
}
PROOF_FILES = (
    ".github/workflows/checks.yml",
    ".github/site/README.md",
    ".github/site/replay_retained_status.py",
    ".github/site/test_replay_retained_status.py",
)
INTENTS = {f"{number:04}" for number in range(1, 7)}
LEDGER_PATH = ".retained-status-proof/dodona.ledger"
OWNER_LEDGER = "records/owner.ledger"
RUST_BINARY = ROOT / "kernel/target/release/dodona-kernel"
JS_BINARY = "kernel2/dodona-kernel2.js"
PROVIDER_CODE = {
    "dodona.tla": ["providers/tlc/provider.py", "providers/tlc/judge.py"],
    "dodona.intent.markdown": ["providers/intents/provider.py", "providers/intents/intents_md.py"],
}


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
    records = command(["git", "diff", "--name-only", "-z", STATUS_SOURCE, RECORDED_SOURCE]).decode().split("\0")
    require(set(records) - {""} == RECORD_PATHS, "recorded Run 15 head differs outside its record paths")
    changed = command(["git", "diff", "--name-only", "-z", RECORDED_SOURCE, head]).decode().split("\0")
    require(set(changed).issubset({"", *PROOF_FILES}), "checkout changes the pinned status source")
    require(not command(["git", "status", "--porcelain", "--untracked-files=all"]), "checkout is dirty")
    return command(["git", "rev-parse", "HEAD^{tree}"]).decode().strip()


def check_source(run: dict, artifact: dict, *, prior: bool = False) -> None:
    run_id, commit, artifact_id, zip_digest = (
        (PRIOR_RUN, PRIOR_COMMIT, PRIOR_ID, PRIOR_ZIP_SHA256) if prior
        else (SOURCE_RUN, SOURCE_COMMIT, ARTIFACT_ID, ZIP_SHA256)
    )
    branch, workflow, events, name, size = (
        ("dodona-eight-3-retained-status", ".github/workflows/checks.yml", ("workflow_dispatch",),
         "issue-3-retained-status-receipt", 106_203) if prior else
        ("main", ".github/workflows/models.yml", ("push", "workflow_dispatch"), "dodona-on-dodona", 191_839)
    )
    label = "prior receipt" if prior else "retained"
    require(
        run.get("id") == run_id and run.get("status") == "completed"
        and run.get("conclusion") == "success" and run.get("head_branch") == branch
        and run.get("event") in events and run.get("head_sha") == commit
        and run.get("path") == workflow
        and run.get("head_repository", {}).get("full_name") == REPOSITORY
        and run.get("repository", {}).get("full_name") == REPOSITORY,
        f"{label} run is not the pinned successful workflow",
    )
    source = artifact.get("workflow_run", {})
    require(
        artifact.get("id") == artifact_id and artifact.get("name") == name
        and artifact.get("expired") is False and artifact.get("size_in_bytes") == size
        and artifact.get("digest") == f"sha256:{zip_digest}" and source.get("id") == run_id
        and source.get("head_sha") == commit and source.get("head_branch") == branch
        and type(source.get("repository_id")) is int and source["repository_id"] == run["repository"].get("id")
        and source.get("head_repository_id") == source.get("repository_id"),
        f"{label} artifact metadata differs from the pinned archive",
    )


def retained_members(raw: bytes, *, prior: bool = False) -> dict[str, bytes]:
    zip_digest, member_digests = (PRIOR_ZIP_SHA256, PRIOR_MEMBERS) if prior else (ZIP_SHA256, MEMBER_DIGESTS)
    label = "prior receipt" if prior else "retained"
    require(digest(raw) == zip_digest, f"{label} archive digest differs")
    members = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name, expected in member_digests.items():
            matching = [member for member in archive.infolist() if member.filename == name]
            require(len(matching) == 1, f"{label} archive needs one {name}")
            members[name] = archive.read(matching[0])
            require(digest(members[name]) == expected, f"{label} {name} digest differs")
    return members


def policy_blob(data: bytes) -> bytes:
    require(digest(data) == POLICY_SHA256, "pinned policy digest differs")
    return data


def check_report(answer: dict, policy_source: str) -> None:
    require("refused" not in answer, f"native status refused: {answer.get('refused')}")
    require(set(answer) == OUT_KEYS, "native status response has the wrong fields")
    require(answer["policy_source"] == policy_source, "native status lost the pinned policy source")
    for field in ("judged", "report"):
        intents = answer[field]["intents"]
        require(isinstance(intents, dict) and set(intents) == INTENTS, f"native {field} lacks the exact six intents")
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
    providers = {
        name: {"command": [sys.executable, "-B", str(ROOT / code[0])], "code": code}
        for name, code in PROVIDER_CODE.items()
    }
    return {
        "root": str(ROOT), "project": "dodona.toml", "policy": policy, "policy_source": policy_source,
        "ledgers": [LEDGER_PATH], "owner_ledger": OWNER_LEDGER,
        "site": {"platform": host.PLATFORM, "writer": "ci", "runner": host.runner_code(),
                 "tools": tools, "providers": providers, "deadline_ms": 10_000},
    }


def request_without_runner_paths(request: dict) -> dict:
    # Validate the provider arguments before replacing the checkout and Python
    # paths that differ across hosted jobs. The policy and ledger paths stay.
    request = deepcopy(request)
    root = Path(request.pop("root"))
    require(root.is_absolute(), "request checkout path is not absolute")
    providers = request["site"]["providers"]
    require(set(providers) == set(PROVIDER_CODE), "request uses different providers")
    for name, code in PROVIDER_CODE.items():
        binding = providers[name]
        argv = binding["command"]
        require(isinstance(argv, list) and len(argv) == 3 and Path(argv[0]).is_absolute()
                and argv[1:] == ["-B", str(root / code[0])] and binding["code"] == code,
                f"request uses different code or arguments for {name}")
        binding["command"] = ["python", "-B", code[0]]
    return request


def comparison_answer(prior: dict[str, bytes], request: dict, ledger: bytes) -> dict:
    summary = read_object(prior["summary.json"])
    require(summary.get("head") == PRIOR_COMMIT and summary.get("status_source") == PRIOR_STATUS_SOURCE
            and summary.get("proof_run") == str(PRIOR_RUN) and summary.get("proof_attempt") == "1"
            and summary.get("scenario_agrees") is True
            and prior["complete.txt"] == b"native status replay completed and scenario report agreed\n",
            "prior receipt has no matching successful completion")
    require(same(summary["source"], {"run": SOURCE_RUN, "head": SOURCE_COMMIT, "artifact": ARTIFACT_ID,
                                     "zip_sha256": ZIP_SHA256, "member_sha256": MEMBER_DIGESTS}),
            "prior receipt used a different historical archive")
    policy_source = request["policy_source"]
    require(same(summary["policy"], {"commit": POLICY_COMMIT, "sha256": POLICY_SHA256, "source": policy_source}),
            "prior receipt used a different policy")
    for key, member in (("request", "request.json"), ("native_status", "native-status.json"),
                        ("scenario_result", "js-final-report.json")):
        require(summary["sha256"][key] == digest(prior[member]), f"prior summary does not bind {member}")
    earlier_request = read_object(prior["request.json"])
    require(same(request_without_runner_paths(earlier_request), request_without_runner_paths(request)),
            "prior and current requests differ beyond runner-local paths")

    answer = read_object(prior["native-status.json"])
    check_report(answer, policy_source)
    check_ledger(answer, ledger)
    require(digest(encode(answer["judged"])) == summary["sha256"]["scenario_input"],
            "prior summary does not bind the judged scenario")
    results = read_object(prior["js-final-report.json"]).get("results")
    require(isinstance(results, list) and len(results) == 1 and same(results[0], answer["report"]),
            "prior receipt's independent final report differs")
    return answer


def compare_output(label: str, answer: dict, expected: dict) -> None:
    for field in sorted(OUT_KEYS):
        require(same(answer[field], expected[field]), f"{label} differs in {field}")


def timed_status(label: str, argv: list[str], request: bytes) -> tuple[bytes, int]:
    print(f"running {label} project status", flush=True)
    started = time.monotonic_ns()
    result = subprocess.run(argv, input=request, cwd=ROOT, timeout=120, capture_output=True, check=True)
    elapsed = time.monotonic_ns() - started
    require(not result.stderr, f"{label} project status emitted diagnostics")
    return result.stdout, elapsed


def read_archive(directory: Path, *, prior: bool = False) -> dict[str, bytes]:
    check_source(read_object((directory / "run.json").read_bytes()),
                 read_object((directory / "artifact.json").read_bytes()), prior=prior)
    return retained_members((directory / "archive.zip").read_bytes(), prior=prior)


def replay(retained: Path, prior: Path, output: Path) -> None:
    head = os.environ["GITHUB_SHA"]
    tree = checkout(head)
    members = read_archive(retained)
    historical = read_object(members["status.json"])
    require(set(historical["intents"]) == INTENTS, "historical status does not cover the same six intents")

    with tempfile.TemporaryDirectory(prefix="retained-status-policy-") as temporary:
        pinned = Path(temporary) / "policy.toml"
        pinned.write_bytes(policy_blob(command(["git", "show", f"{POLICY_COMMIT}:policy.toml"])))
        policy = read_object(command([sys.executable, "-B", "tools/policy_input.py", str(pinned)]))
    policy_source = f"{REPOSITORY}@{POLICY_COMMIT}:policy.toml sha256:{POLICY_SHA256}"
    request = status_input(policy, policy_source)
    request_bytes = encode(request)
    previous = comparison_answer(read_archive(prior, prior=True), request, members["dodona.ledger"])

    ledger = ROOT / LEDGER_PATH
    ledger.parent.mkdir()
    raw = {}
    answers = {}
    elapsed_ns = {}
    try:
        with ledger.open("xb") as destination:
            destination.write(members["dodona.ledger"])
        for name, argv in (("rust", [str(RUST_BINARY), "status"]), ("javascript", ["node", JS_BINARY, "status"])):
            raw[name], elapsed_ns[name] = timed_status(name, argv, request_bytes)
            answer = read_object(raw[name])
            check_report(answer, policy_source)
            check_ledger(answer, members["dodona.ledger"])
            require(same(answer["policy_not_applied"], policy["not_applied"]), f"{name} lost policy limitations")
            require(digest(ledger.read_bytes()) == MEMBER_DIGESTS["dodona.ledger"], f"{name} changed the retained ledger")
            answers[name] = answer
    finally:
        ledger.unlink(missing_ok=True)
        ledger.parent.rmdir()

    answer = answers["rust"]
    compare_output("native pair", answers["javascript"], answer)
    compare_output("native pair versus prior receipt", answer, previous)

    summary = {
        "head": head, "tree": tree, "status_source": STATUS_SOURCE,
        "recorded_source": RECORDED_SOURCE, "qualification_head": QUALIFICATION_HEAD,
        "proof_run": os.environ["GITHUB_RUN_ID"], "proof_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "source": {"run": SOURCE_RUN, "head": SOURCE_COMMIT, "artifact": ARTIFACT_ID,
                   "zip_sha256": ZIP_SHA256, "member_sha256": MEMBER_DIGESTS},
        "prior": {"run": PRIOR_RUN, "head": PRIOR_COMMIT, "artifact": PRIOR_ID,
                  "zip_sha256": PRIOR_ZIP_SHA256, "member_sha256": PRIOR_MEMBERS},
        "policy": {"commit": POLICY_COMMIT, "sha256": POLICY_SHA256, "source": answer["policy_source"]},
        "site": {key: value for key, value in request["site"].items() if key != "providers"},
        "host": {"os": platform.system(), "machine": platform.machine(), "python": platform.python_version(),
                 "node": command(["node", "--version"]).decode().strip(),
                 "rustc": command(["rustc", "--version"]).decode().strip()},
        "sha256": {"request": digest(request_bytes), "judged": digest(encode(answer["judged"])),
                   "rust_status": digest(raw["rust"]), "javascript_status": digest(raw["javascript"]),
                   "rust_binary": digest(RUST_BINARY.read_bytes())},
        "comparison": {"steps": len(answer["judged"]["steps"]), "fields": sorted(OUT_KEYS),
                       "native_pair_agrees": True, "prior_receipt_agrees": True,
                       "native_status_elapsed_ns": elapsed_ns},
        "intents": answer["report"]["intents"],
        "obligation_statuses": Counter(item["status"] for item in answer["report"]["obligations"].values()),
        "project": answer["report"]["project"], "project_status": answer["project_status"],
        "project_doubts": answer["project_doubts"], "policy_not_applied": answer["policy_not_applied"],
        "ledger": answer["ledger"],
    }
    output.mkdir()
    (output / "request.json").write_bytes(request_bytes)
    (output / "rust-status.json").write_bytes(raw["rust"])
    (output / "javascript-status.json").write_bytes(raw["javascript"])
    (output / "summary.json").write_bytes(encode(summary) + b"\n")
    (output / "complete.txt").write_text("native status pair and prior receipt agree\n", encoding="utf-8")
    print(encode(summary).decode())
    print("native status pair and prior receipt agree")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check-checkout", action="store_true")
    parser.add_argument("retained", type=Path, nargs="?")
    parser.add_argument("prior", type=Path, nargs="?")
    parser.add_argument("receipt", type=Path, nargs="?")
    args = parser.parse_args()
    try:
        paths = (args.retained, args.prior, args.receipt)
        if args.check_checkout and all(path is None for path in paths):
            print(checkout(os.environ["GITHUB_SHA"]))
        elif not args.check_checkout and all(path is not None for path in paths):
            replay(*paths)
        else:
            parser.error("give --check-checkout or all of RETAINED, PRIOR and RECEIPT")
    except (ValueError, OSError, KeyError, IndexError, TypeError, zipfile.BadZipFile, host.Refused, subprocess.SubprocessError) as error:
        raise SystemExit(f"retained status replay stopped: {error}") from None
