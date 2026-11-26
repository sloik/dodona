"""Bind the model workflow's native requests to its exact push checkout.

    python .github/site/model_request.py prepare-policy COMMIT
    python .github/site/model_request.py dump-plan DUMPS_DIR
    python .github/site/model_request.py run COMMIT POLICY.json
    python .github/site/model_request.py status COMMIT POLICY.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import canonical  # noqa: E402
import host  # noqa: E402
import policy_input  # noqa: E402

EXECUTOR = ".github/site/executor.json"
LEDGER = "out/dodona.ledger"
RUNNER_FILES = (EXECUTOR, ".github/site/batch_driver.py", ".github/site/kernel_executor.py", "tools/host.py")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "--no-replace-objects", *args], cwd=ROOT)


def policy_at(commit: str, *, validate: bool = False) -> dict:
    """Only the event's checkout can supply the policy used by this workflow."""
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit) is None:
        raise ValueError("the protected push must identify its checkout by full commit id")
    if git("rev-parse", "--verify", "HEAD").decode("ascii").strip() != commit:
        raise ValueError("the checkout is not the protected push commit")
    raw = git("show", f"{commit}:policy.toml")
    policy = tomllib.loads(raw.decode("utf-8"))
    if validate:
        policy_input.validate(policy)
    return {"commit": commit, "identity": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "policy": policy_input.reduce(policy)}


def policy_from_artifact(commit: str, path: pathlib.Path) -> dict:
    expected = policy_at(commit)
    supplied = host.strict_load(path.read_bytes())
    if canonical.identity(supplied) != canonical.identity(expected):
        raise ValueError("the policy artifact differs from the protected checkout")
    return expected


def site_settings() -> dict:
    return json.loads((ROOT / EXECUTOR).read_text(encoding="utf-8"))


def runner_identity() -> str:
    files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in RUNNER_FILES}
    return canonical.identity(files)


def dump_plan(kept: pathlib.Path) -> dict:
    """Plan the state-dump work without planning any model obligation."""
    keys = {path.parent.name: host.dump_key(path.parent) for path in sorted(ROOT.glob("spec/*/dump.cfg"))}
    index = kept / "dumps.json"
    previous = json.loads(index.read_text(encoding="utf-8")) if index.is_file() else {}
    reuse = [name for name, key in keys.items()
             if previous.get(name) == key and (kept / name / "dump.states.dump").is_file()]
    return {"run": [], "reuse": [], "dumps_run": sorted(set(keys) - set(reuse)),
            "dumps_reuse": sorted(reuse), "dump_keys": keys}


def request(policy: dict, *, run: bool) -> dict:
    bound = {
        "root": str(ROOT),
        "project": "dodona.toml",
        "site": {
            "platform": host.PLATFORM,
            "writer": "ci",
            "runner": runner_identity(),
            "tools": host.lock_tools()[0],
            "deadline_ms": 30_000,
            "providers": {
                "dodona.tla": {"command": [sys.executable, "providers/tlc/provider.py"],
                               "code": ["providers/tlc/provider.py", "providers/tlc/judge.py"]},
                "dodona.intent.markdown": {"command": [sys.executable, "providers/intents/provider.py"],
                                           "code": ["providers/intents/provider.py", "providers/intents/intents_md.py"]},
            },
        },
        "policy": policy["policy"],
        "policy_source": f"policy.toml at {policy['commit']} ({policy['identity']})",
        "owner_ledger": "records/owner.ledger",
        "ledgers": [LEDGER],
    }
    if run:
        bound.update(ledger=LEDGER, executor=[sys.executable, ".github/site/kernel_executor.py", EXECUTOR],
                     transcript="out/model-transcript.json", batch_wait_floor_ms=site_settings()["native_batch_wait_floor_ms"])
    return bound


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    prepare = commands.add_parser("prepare-policy")
    prepare.add_argument("commit")
    dumps = commands.add_parser("dump-plan")
    dumps.add_argument("kept", type=pathlib.Path)
    for name in ("run", "status"):
        mode = commands.add_parser(name)
        mode.add_argument("commit")
        mode.add_argument("artifact", type=pathlib.Path)
    args = parser.parse_args()
    try:
        if args.mode == "prepare-policy":
            result = policy_at(args.commit, validate=True)
        elif args.mode == "dump-plan":
            result = dump_plan(args.kept)
        else:
            result = request(policy_from_artifact(args.commit, args.artifact), run=args.mode == "run")
    except (OSError, ValueError, subprocess.CalledProcessError, host.Refused, policy_input.NotValid) as err:
        print(f"model request refused: {err}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
