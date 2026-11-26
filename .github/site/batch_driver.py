"""Runs a list of model-checker cases one after another, inside the executor.

Part of this repository's own site binding (decision 0023). It is the only
place in the repository that starts the model checker, and it is meant to be
run by the site's executor in its sandbox, never directly: one executor job
for the whole list is kinder to a shared queue than one job per case.

    python3 batch_driver.py manifest.json

The manifest lists cases, each with a working directory, an argument list and
a name. A supplied wall_ms bounds that case's process. The driver writes
<out>/<name>.txt with the checker's output and <out>/<name>.exit with its exit
status, "did-not-start" or "timed-out". A timeout leaves diagnostic output
and discards any partial kept file. Run anywhere but inside a job of the
queue, the driver refuses with exit status 78 before reading anything.
"""
import hashlib
import json
import re
import pathlib
import shutil
import subprocess
import sys


def inside_the_executor() -> bool:
    """True only inside a job of this site's queue.

    The driver starts the model checker, and this site allows that in one
    place only. Every fact below is set by the queue for its jobs and cannot
    be arranged by whoever runs this file by hand: a marker in the
    environment alone is not enough.
    """
    import os
    import re
    job = os.environ.get("TLA_QUEUE_JOB", "")
    if not sys.platform.startswith("linux") or not re.fullmatch(r"[0-9a-f]{32}", job):
        return False
    try:
        import pwd
        worker = pwd.getpwnam("tla-job").pw_uid
        if not (os.getuid() == os.geteuid() == worker) or pwd.getpwuid(os.getuid()).pw_name != "tla-job":
            return False
        groups = pathlib.Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
    except (KeyError, OSError, ValueError):
        return False
    return groups == [f"0::/system.slice/tla-q-{job}.service"]


def stated_version(printed: bytes, exit_status: int) -> str | None:
    """The version a Java runtime states on its own line, `openjdk version "21.0.13" ...` or `java version "..."`; None
    unless it exited 0 and the version is a release (digits and dots only: `21.0.13-ea` is not one)."""
    if exit_status != 0:
        return None
    for line in printed.decode("utf-8", "replace").splitlines():
        found = re.fullmatch(r'(?:openjdk|java) version "([0-9]+(?:\.[0-9]+)*)"(?: .*)?', line.strip())
        if found:
            return found.group(1)
    return None


def main() -> int:
    if not inside_the_executor():
        print("refused: this driver runs only inside a job of the site's queue", file=sys.stderr)
        return 78
    manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = pathlib.Path(manifest["out"])
    out.mkdir(parents=True, exist_ok=True)
    # What is about to be run: the digest of each program and library the site asked to have
    # measured. Done before the first case, so it is there even if the job is stopped later.
    measured = {}
    for path in manifest.get("measure", []):
        try:
            measured[path] = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
        except OSError:
            measured[path] = None
    (out / "measured.json").write_text(json.dumps(measured, indent=1), encoding="utf-8")
    # The version of each program pinned by a floor, as the program states it (`java -version` prints
    # `version "21.0.13"` on its first line). Unreadable is null, which never meets a floor.
    versions = {}
    for path in manifest.get("versions", []):
        try:
            said = subprocess.run([path, "-version"], capture_output=True, timeout=60)
            versions[path] = stated_version(said.stderr + said.stdout, said.returncode)
        except (OSError, subprocess.TimeoutExpired):
            versions[path] = None
    (out / "versions.json").write_text(json.dumps(versions, indent=1), encoding="utf-8")
    for case in manifest["cases"]:
        target = out / case["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        timeout = max(case["wall_ms"], 0) / 1000 if "wall_ms" in case else None
        try:
            done = subprocess.run(case["argv"], cwd=case["cwd"], capture_output=True, timeout=timeout)
            output, status = done.stdout + done.stderr, str(done.returncode)
        except subprocess.TimeoutExpired as err:
            output, status = (err.stdout or b"") + (err.stderr or b""), "timed-out"
        except OSError as err:
            output, status = f"could not start: {err}\n".encode("utf-8"), "did-not-start"
        target.with_suffix(".txt").write_bytes(output)
        target.with_suffix(".exit").write_text(status, encoding="ascii")
        for extra in case.get("keep", []):  # files the case produced that should come back
            source = pathlib.Path(case["cwd"]) / extra
            if source.exists():
                if status != "timed-out":
                    (out / (case["name"] + "." + extra)).write_bytes(source.read_bytes())
                source.unlink()
        # The checker leaves its working files behind. Left to pile up over many
        # cases they would exhaust the space a job is allowed.
        shutil.rmtree(pathlib.Path(case["cwd"]) / "states", ignore_errors=True)
    # Written last, so a job that was stopped part of the way has no such file
    # and nothing from it can be taken for the result of a whole job.
    (out / "complete.json").write_text(json.dumps({"cases": [case["name"] for case in manifest["cases"]]}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
