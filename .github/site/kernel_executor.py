"""This site's batch executor for a kernel's `run` command (decision 0034). Part of the site, not of dodona.

    python3 .github/site/kernel_executor.py .github/site/executor.json < BATCH

A kernel starts this once per batch, in the project root, with `{"runs": [{"number", "run_key", "run"}]}` on
standard input. It sends the whole batch to the site's queue as one job, run by batch_driver.py, and answers on one
line `{"ended": true, "reports": [{"run_key", "report"}]}`, or exits non-zero when the queue could not be reached,
which the kernel reads as `unavailable` for every run of the batch. It judges nothing; it reports what ran:

- Each run's inputs are copied into the job from the project, and only they. A file whose identity is not the one
  the run names is not sent: that run's report ends `cancelled`, which the kernel reads as an error.
- A fixed pin is reported with the digest measured. A measured version at or above the site's floor is reported
  with the site's floor key. Other version measurements keep the measured file digest. Missing measurements use
  zeros. The kernel compares these keys with the ones requested and treats a mismatch as an error.
- A job that did not end well, or whose end marker does not list every run, gives every run the end `cancelled`.
- The run's wall limit goes to the case driver. A case that times out in a completed job is reported as
  `timed-out` with diagnostic output and without an exit status.
- What each run printed is kept under out/kernel-runs/, inside the project, where the provider reads it.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path.cwd()
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import host  # noqa: E402

PLATFORM = host.PLATFORM
KEPT = pathlib.Path("out") / "kernel-runs"


def identity(path: pathlib.Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def argv_of(run: dict, where: dict) -> list[str] | None:
    """The command line on the executor's machine: the program and every ${tool:...} file mapped to this site's files."""
    try:
        argv = [where[f"{run['program']['tool']}/{run['program']['path']}"]]
        argv += [host.TOOL_FILE.sub(lambda m: where[f"{m.group(1)}/{m.group(2)}"], arg) for arg in run.get("args", [])]
    except (KeyError, TypeError):
        return None
    return argv


def tools_ran(run: dict, pinned: dict, measured: dict, versions: dict) -> list[dict]:
    """Report measured digests and verified site floor keys."""
    unmeasured, mismatched = host.tool_faults(pinned, measured, versions)
    ran = []
    for tool in run.get("tools", []):
        name = tool.get("name")
        pin = pinned.get(name)
        seen = measured.get(pin["file"]) if pin else None
        if pin is not None and pin.get("floor") and name not in unmeasured and name not in mismatched:
            seen = host.floor_digest(pin)
        ran.append({"name": name, "digest": "sha256:" + (seen or "0" * 64)})
    return ran


def main() -> int:
    site = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    batch = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    where = site["tool_files"]
    _, pinned = host.lock_tools()
    work = pathlib.Path(tempfile.mkdtemp(prefix="dodona-batch-"))
    bundle = work / "bundle"
    bundle.mkdir()
    cases, ended, names = [], {}, {}
    for item in batch["runs"]:
        run, key = item["run"], item["run_key"]
        name = f"runs/r{item['number']}-{key.removeprefix('sha256:')[:16]}"  # in a folder, as the job's outputs are read
        names[key] = name
        argv = argv_of(run, where)
        inputs_ok = argv is not None
        for each in run.get("inputs", []) if inputs_ok else []:
            source = ROOT / each["path"]
            if identity(source) != each["identity"]:
                inputs_ok = False  # not the file the run names: it is not sent
                break
            target = bundle / name / each["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        if not inputs_ok:
            ended[key] = "cancelled"
            continue
        case = {"name": name, "cwd": (pathlib.PurePosixPath(name) / run.get("cwd", ".")).as_posix(), "argv": argv}
        limits = run.get("limits")
        if isinstance(limits, dict) and "wall_ms" in limits:
            case["wall_ms"] = limits["wall_ms"]
        cases.append(case)
    with contextlib.redirect_stdout(sys.stderr):  # standard output carries the answer and nothing else
        job = host.send_job(site, bundle, cases) if cases else None
    job = job or {"reachable": True, "complete": True, "fetched": None, "measured": {}, "versions": {}}
    if not job["reachable"]:
        print("the queue could not be reached; nothing ran", file=sys.stderr)
        return 1
    # Both by the site's tool file names (java/bin/java), as the pins name them.
    measured, versions = job["measured"], job["versions"]
    kept = ROOT / KEPT
    kept.mkdir(parents=True, exist_ok=True)
    reports = []
    for item in batch["runs"]:
        key, name, run = item["run_key"], names[item["run_key"]], item["run"]
        report = {"handle": name, "platform": PLATFORM, "tools_ran": tools_ran(run, pinned, measured, versions),
                  "isolation": "best-effort", "outputs": []}
        printed = job["fetched"] / f"{name}.txt" if job.get("fetched") else None
        status = job["fetched"] / f"{name}.exit" if job.get("fetched") else None
        captured = kept / f"{pathlib.PurePosixPath(name).name}.txt"
        report["end"] = ended.get(key, "cancelled")
        if key not in ended and job["complete"] and printed and printed.is_file() and status.is_file():
            outcome = status.read_text(encoding="ascii").strip()
            if outcome == "timed-out":
                report["end"] = "timed-out"
            elif outcome.removeprefix("-").isdigit():
                report.update(end="exited", exit_status=int(outcome))
        if report["end"] == "cancelled":
            captured.write_bytes(b"")
        else:
            shutil.copyfile(printed, captured)
        report["captured_output"] = {"path": captured.relative_to(ROOT).as_posix(), "identity": identity(captured)}
        reports.append({"run_key": key, "report": report})
    sys.stdout.buffer.write(json.dumps({"ended": True, "reports": reports}).encode("utf-8") + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
