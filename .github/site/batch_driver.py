"""Runs a list of model-checker cases one after another, inside the executor.

Part of this repository's own site binding (decision 0023). It is the only
place in the repository that starts the model checker, and it is meant to be
run by the site's executor in its sandbox, never directly: one executor job
for the whole list is kinder to a shared queue than one job per case.

    python3 batch_driver.py manifest.json

The manifest lists cases, each with a working directory, an argument list and
a name. For each case the driver writes <out>/<name>.txt with the checker's
output and <out>/<name>.exit with its exit status. A case that cannot be
started gets the exit status "did-not-start". The driver itself judges
nothing; tools/check_models.py does that from the files.
"""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys


def main() -> int:
    manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = pathlib.Path(manifest["out"])
    for case in manifest["cases"]:
        target = out / case["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            done = subprocess.run(case["argv"], cwd=case["cwd"], capture_output=True)
            target.with_suffix(".txt").write_bytes(done.stdout + done.stderr)
            target.with_suffix(".exit").write_text(str(done.returncode), encoding="ascii")
        except OSError as err:
            target.with_suffix(".txt").write_text(f"could not start: {err}\n", encoding="utf-8")
            target.with_suffix(".exit").write_text("did-not-start", encoding="ascii")
        for extra in case.get("keep", []):  # files the case produced that should come back
            source = pathlib.Path(case["cwd"]) / extra
            if source.exists():
                (out / (case["name"] + "." + extra)).write_bytes(source.read_bytes())
                source.unlink()
        # The checker leaves its working files behind. Left to pile up over many
        # cases they would exhaust the space a job is allowed.
        shutil.rmtree(pathlib.Path(case["cwd"]) / "states", ignore_errors=True)
    # What was actually run: the digest of each program and library the site asked to have measured.
    measured = {}
    for path in manifest.get("measure", []):
        try:
            measured[path] = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
        except OSError:
            measured[path] = None
    (out / "measured.json").write_text(json.dumps(measured, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
