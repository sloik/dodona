"""This site's executor for runs that need no shared queue: tests run on the CI machine itself (decision 0035).
Part of the site, not of dodona.

    python3 .github/site/local_executor.py .github/site/local-executor.json < BATCH

A kernel starts this once per batch, in the project root, with `{"runs": [{"number", "run_key", "run"}]}` on
standard input, and it answers on one line `{"ended": true, "reports": [{"run_key", "report"}]}`. For each run:

- A run whose program is a tool this site does not run here (the model checker, which runs on the shared queue)
  ends `unavailable`, which is never recorded: another run of the kernel, with the queue's executor, takes it.
- Its inputs are copied, and only they, into a fresh folder; a file whose identity is not the one the run names is
  not copied, and the run ends `cancelled`, which the kernel reads as an error.
- The program runs in that folder, in the run's working directory, with the run's wall limit; what it printed is
  kept under out/local-runs/, where the provider reads it. A run past its limit ends `timed-out`.
- Each tool the run asks for is reported as asked only when this machine's copy meets the site's pin (a version at
  or above the floor); otherwise with the digest measured, so the kernel finds a tool other than the one asked for
  and the check ends in error, never with a verdict.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from typing import NamedTuple

ROOT = pathlib.Path.cwd()
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import host  # noqa: E402

KEPT = pathlib.Path("out") / "local-runs"


def child_environment() -> dict[str, str]:
    return {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT") if key in os.environ}


def identity(path: pathlib.Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class Runtime(NamedTuple):
    executable: str
    digest: str
    version: str
    platform: dict[str, str]


def measure(program: str) -> Runtime | None:
    found = shutil.which(program)
    if found is None:
        return None
    executable = pathlib.Path(found).resolve()
    probe = ("JSON.stringify({version: process.versions.node, os: process.platform, arch: process.arch,"
             "glibc: process.report?.getReport().header.glibcVersionRuntime})")
    try:
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        result = subprocess.run([str(executable), "-p", probe], capture_output=True, timeout=60, check=True)
        fields = json.loads(result.stdout)
        os_name = {"darwin": "macos", "linux": "linux", "win32": "windows"}[fields["os"]]
        arch = {"arm64": "aarch64", "x64": "x86_64"}[fields["arch"]]
        version = fields["version"]
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version) is None:
            return None
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError):
        return None
    platform = {"os": os_name, "arch": arch}
    if os_name == "linux" and isinstance(fields.get("glibc"), str):
        platform["libc"] = "gnu"
    return Runtime(str(executable), digest, version, platform)


def main() -> int:
    site = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    batch = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    pinned = {pin["name"]: pin for pin in site["pins"]}
    here = {name: runtime for name, program in site["programs"].items() if (runtime := measure(program))}
    measured = {pinned[name]["file"]: runtime.digest for name, runtime in here.items() if name in pinned}
    versions = {pinned[name]["file"]: runtime.version for name, runtime in here.items() if name in pinned}
    unmeasured, mismatched = host.tool_faults({n: pinned[n] for n in here if n in pinned}, measured, versions)
    floor_keys = {name: "sha256:" + host.floor_digest(pin) for name, pin in pinned.items()}
    kept = ROOT / KEPT
    kept.mkdir(parents=True, exist_ok=True)
    reports = []
    for item in batch["runs"]:
        run, key = item["run"], item["run_key"]
        name = f"r{item['number']}-{key.removeprefix('sha256:')[:16]}"
        tool = (run.get("program") or {}).get("tool")
        runtime = here.get(tool)
        request_platform = run.get("platform")
        matches = (runtime is not None and isinstance(request_platform, dict) and {"os", "arch"} <= request_platform.keys()
                   and all(field in runtime.platform and runtime.platform[field] == value
                           for field, value in request_platform.items()))
        reported_platform = request_platform if matches or runtime is None else runtime.platform
        ran = []
        for asked in run.get("tools", []):
            tool_name = asked.get("name")
            if tool_name not in here:
                continue
            digest = "sha256:" + here[tool_name].digest
            if tool_name in floor_keys and tool_name not in unmeasured and tool_name not in mismatched:
                digest = floor_keys[tool_name]
            ran.append({"name": tool_name, "digest": digest})
        report = {"handle": name, "platform": reported_platform, "tools_ran": ran, "isolation": "best-effort", "outputs": []}
        captured = kept / f"{name}.txt"
        captured.write_bytes(b"")
        if not matches:
            report["end"] = "unavailable"
        elif ran != run.get("tools", []):
            report["end"] = "cancelled"
        else:
            with tempfile.TemporaryDirectory(prefix="dodona-local-") as tmp:
                work = pathlib.Path(tmp)
                complete = True
                for each in run.get("inputs", []):
                    source = ROOT / each["path"]
                    if identity(source) != each["identity"]:
                        complete = False  # not the file the run names: it is not run
                        break
                    target = work / each["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                if not complete:
                    report["end"] = "cancelled"
                else:
                    wall = (run.get("limits") or {}).get("wall_ms")
                    argv = [runtime.executable, *run.get("args", [])]
                    try:
                        done = subprocess.run(argv, cwd=work / run.get("cwd", "."), capture_output=True,
                                              timeout=wall / 1000 if isinstance(wall, int) and wall > 0 else None,
                                              env=child_environment())
                        captured.write_bytes(done.stdout + done.stderr)
                        report.update(end="exited", exit_status=done.returncode)
                    except subprocess.TimeoutExpired as err:
                        captured.write_bytes((err.stdout or b"") + (err.stderr or b""))
                        report["end"] = "timed-out"
                    except OSError:
                        report["end"] = "unavailable"
        report["captured_output"] = {"path": captured.relative_to(ROOT).as_posix(), "identity": identity(captured)}
        reports.append({"run_key": key, "report": report})
    sys.stdout.buffer.write(json.dumps({"ended": True, "reports": reports}).encode("utf-8") + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
