"""Capture and bind one passing receipt on the manual JavaScript fallback lane.

    python .github/site/js_shard_proof.py capture SOURCE OUT INDEX
    python .github/site/js_shard_proof.py bind OUT INDEX
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO

SOURCE = "a51578c688adb6fee3970057d68c97286911873f"
MANIFEST_SHA256 = "f06ffd803d8000ed3821f0b8533f9966ed92fa7af255a5020557637277d71e00"
INVENTORY_COUNT = 319
SHARD_COUNT = 5
REPOSITORY = "sloik/dodona"
PROOF_REF = "refs/heads/dodona-eight-41-js-fallback-qualified"
WORKFLOW_REF = f"{REPOSITORY}/.github/workflows/checks.yml@{PROOF_REF}"
JOB = "js-shard-fallback"


def git_output(source: Path, *command: str) -> str:
    return subprocess.run(["git", *command], cwd=source, check=True, capture_output=True, text=True).stdout.strip()


def inventory(source: Path) -> list[dict]:
    if git_output(source, "rev-parse", "--verify", "HEAD") != SOURCE or git_output(source, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("source checkout is not clean at the pinned revision")
    manifest = (source / "kernel2" / "defects.json").read_bytes()
    if hashlib.sha256(manifest).hexdigest() != MANIFEST_SHA256:
        raise ValueError("raw defect manifest SHA-256 differs from the pinned inventory")
    names = [defect["name"] for defect in read_object(manifest)["defects"]]
    if len(names) != INVENTORY_COUNT or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("pinned manifest lacks the exact named inventory")
    if len(set(names)) != INVENTORY_COUNT:
        raise ValueError("pinned manifest repeats a defect name")
    return [{"index": index, "name": name} for index, name in enumerate(names, start=1)]


def positive_number(value: str, label: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError(f"missing or invalid {label}")
    return int(value)


def binding(index: int) -> dict:
    if SOURCE is None or not re.fullmatch(r"[0-9a-f]{40}", SOURCE):
        raise ValueError("JavaScript shard source has not been pinned")
    if not 1 <= index <= SHARD_COUNT:
        raise ValueError("shard index is outside the fixed plan")
    plan = {"GITHUB_REPOSITORY": REPOSITORY, "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": PROOF_REF,
            "GITHUB_WORKFLOW_REF": WORKFLOW_REF, "GITHUB_JOB": JOB}
    if any(os.environ.get(key) != value for key, value in plan.items()):
        raise ValueError("this job is outside the manual fallback lane")
    workflow_sha = os.environ.get("GITHUB_WORKFLOW_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", workflow_sha) or workflow_sha != os.environ.get("GITHUB_SHA"):
        raise ValueError("missing or inconsistent workflow revision")
    run_id = positive_number(os.environ.get("GITHUB_RUN_ID", ""), "run id")
    attempt = positive_number(os.environ.get("GITHUB_RUN_ATTEMPT", ""), "run attempt")
    return {"repository": REPOSITORY, "workflow_ref": WORKFLOW_REF, "workflow_sha": workflow_sha,
            "run_id": run_id, "run_attempt": attempt, "job": JOB,
            "source_sha": SOURCE, "manifest_sha256": MANIFEST_SHA256,
            "shard": {"index": index, "count": SHARD_COUNT},
            "artifact_name": f"issue41-js-{run_id}-{attempt}-shard-{index}-of-{SHARD_COUNT}"}


def distinct_fields(pairs: list[tuple[str, object]]) -> dict:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("repeated field in JSON record")
    return result


def read_object(data: bytes):
    return json.loads(data.decode("utf-8"), object_pairs_hook=distinct_fields)


def same_record(actual, expected: dict) -> bool:
    # JSON true and 1 compare equal in Python but differ in a receipt.
    return json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def validate_footer(footer: bytes, index: int, selected: list[dict]) -> None:
    expected = {"defects": len(selected), "caught": len(selected), "unfinished": 0, "all_caught": False,
                "missed": 0, "stale": 0, "broken": 0, "caught_provisionally": 0, "caught_without_mismatch": 0,
                "finished": True, "cleaned_up": True,
                "shard": {"index": index, "count": SHARD_COUNT}, "baseline_passed": True, "shard_passed": True,
                "inventory": {"sha256": MANIFEST_SHA256, "count": INVENTORY_COUNT}, "covered": selected}
    if not footer.endswith(b"\n") or not same_record(read_object(footer), expected):
        raise ValueError("final footer does not establish a clean baseline and exact passing shard coverage")


def judge(source: Path, index: int, log: BinaryIO) -> bytes:
    command = ["node", "kernel2/plant.js", "--shard", f"{index}/{SHARD_COUNT}"]
    footer = b""
    with subprocess.Popen(command, cwd=source, stdout=subprocess.PIPE) as process:
        for line in process.stdout:
            log.write(line)
            log.flush()
            footer = line
        if process.wait() != 0:
            raise ValueError("the shard command did not exit successfully")
    return footer


def capture(source: Path, out: Path, index: int, log: BinaryIO) -> None:
    provenance = binding(index)  # verify the lane and attempt before starting a judge
    expected = inventory(source)
    selected = expected[index - 1::SHARD_COUNT]
    footer = judge(source, index, log)
    validate_footer(footer, index, selected)
    provenance["footer_sha256"] = hashlib.sha256(footer).hexdigest()
    out.mkdir()  # Publication always uses a fresh directory owned by this job.
    (out / "receipt.json").write_bytes(footer)
    (out / "binding.json").write_text(json.dumps(provenance) + "\n", encoding="utf-8")


def bind(out: Path, index: int) -> dict:
    provenance = binding(index)
    provenance["footer_sha256"] = hashlib.sha256((out / "receipt.json").read_bytes()).hexdigest()
    if not same_record(read_object((out / "binding.json").read_bytes()), provenance):
        raise ValueError("artifact payload differs from this attempt's prepared binding")
    artifact_id = positive_number(os.environ.get("PROOF_ARTIFACT_ID", ""), "artifact id")
    digest = os.environ.get("PROOF_ARTIFACT_DIGEST", "").removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("missing or invalid artifact SHA-256")
    return dict(provenance, artifact_id=artifact_id, artifact_sha256=digest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("capture")
    collect.add_argument("source", type=Path)
    publish = commands.add_parser("bind")
    for command in (collect, publish):
        command.add_argument("out", type=Path)
        command.add_argument("index", type=int)
    args = parser.parse_args()
    try:
        if args.command == "capture":
            capture(args.source, args.out, args.index, sys.stdout.buffer)
        else:
            print("ISSUE41_JS_SHARD_ARTIFACT " + json.dumps(bind(args.out, args.index)))
    except (OSError, ValueError, RecursionError, subprocess.CalledProcessError) as error:
        print(f"UNFINISHED: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
