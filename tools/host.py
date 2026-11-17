"""Runs a project's checks through a provider, an executor and a kernel.

Stage-0 helper (decision 0026). This is the first time the pieces are joined:
a provider lists obligations and describes the runs it needs, the site's
executor performs them as one job, the provider interprets what came back, and
a kernel writes the results to a ledger and reports status.

It is in two halves, because the executor and the kernel may live on
different machines:

    python tools/host.py collect  --site FILE --out DIR
    python tools/host.py conclude --runs DIR --ledger FILE --writer NAME --kernel CMD...

`collect` needs the executor. It asks the provider what to run, has it run,
and saves what came back. `conclude` needs a kernel. It gives the provider the
saved results, checks what the provider says against the rules a schema cannot
express, and records the verdicts.

The host enforces: an answer matches its request; a verdict rests on a run; a
result does not claim more strength than the manifest declares; a program lies
inside a tool the provider declared; every path passes the path check; a run
that did not exit ends the check in error. Every message of a session is kept
in a transcript, so it can be validated against the schemas afterwards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402
import pathcheck  # noqa: E402
import provider_host  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RANKS = ["documented", "sampled", "bounded", "exhaustive"]
PLATFORM = {"os": "linux", "arch": "aarch64", "libc": "gnu"}


class Refused(Exception):
    """The provider broke a rule. The reason is a stable code."""


def file_ref(path: pathlib.Path, root: pathlib.Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "identity": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()}


class Session:
    """One provider process, with the rules about messages applied to it."""

    def __init__(self, argv: list[str], cwd: pathlib.Path, transcript: list, deadline_s: float = 60):
        import queue
        import threading
        self.tree = provider_host.Tree(argv) if cwd == pathlib.Path.cwd() else self._start(argv, cwd)
        self.lines: "queue.Queue" = queue.Queue()
        self.transcript, self.deadline_s, self.next_id = transcript, deadline_s, 0
        log = {"bytes": 0, "kept": b"", "truncated": False}
        threading.Thread(target=provider_host.read_lines, args=(self.tree.proc.stdout, 1048576, self.lines), daemon=True).start()
        threading.Thread(target=provider_host.drain, args=(self.tree.proc.stderr, 65536, log), daemon=True).start()
        echo = "héllo ☃ \u0001\u001f end"
        self.send({"type": "hello", "protocol": ["0.2"], "limits": {"max_line_bytes": 1048576, "deadline_ms": int(deadline_s * 1000)}, "echo": echo})
        answer = self.receive()
        if answer.get("type") != "manifest" or answer.get("echo") != echo:
            raise Refused("bad-manifest")
        self.manifest = answer["manifest"]

    @staticmethod
    def _start(argv, cwd):
        import os
        here = os.getcwd()
        os.chdir(cwd)
        try:
            return provider_host.Tree(argv)
        finally:
            os.chdir(here)

    def send(self, message: dict) -> None:
        self.transcript.append({"to": "provider", "message": message})
        try:
            self.tree.proc.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
            self.tree.proc.stdin.flush()
        except OSError:
            raise Refused("closed") from None

    def receive(self) -> dict:
        import queue
        try:
            kind, raw = self.lines.get(timeout=self.deadline_s)
        except queue.Empty:
            raise Refused("deadline") from None
        if kind != "line":
            raise Refused("closed" if kind == "closed" else "too-long")
        if raw.startswith(b"\xef\xbb\xbf") or raw.endswith(b"\r"):
            raise Refused("framing")
        try:
            message = json.loads(raw.decode("utf-8"), object_pairs_hook=no_repeats, parse_float=no_fractions)
        except UnicodeDecodeError:
            raise Refused("encoding") from None
        except ValueError as err:
            raise Refused(str(err) if str(err) in ("duplicate-key", "not-an-integer") else "malformed") from None
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            raise Refused("malformed")
        self.transcript.append({"to": "kernel", "message": message})
        return message

    def ask(self, capability: str, body: dict) -> dict:
        """Send one request and return the body of its result."""
        self.next_id += 1
        ident = str(self.next_id)
        self.send({"type": "request", "id": ident, "deadline_ms": int(self.deadline_s * 1000), "capability": capability, "body": body})
        answer = self.receive()
        if answer.get("id") != ident:
            raise Refused("wrong-id")
        if answer.get("type") == "error":
            raise Refused("provider-error")
        if answer.get("type") != "result" or not isinstance(answer.get("body"), dict):
            raise Refused("unexpected")
        if answer.get("capability") != capability:
            raise Refused("wrong-capability")
        self.last_request = ident
        return answer["body"]

    def close(self) -> None:
        try:
            self.send({"type": "shutdown"})
        except Refused:
            pass
        self.tree.end()


def no_repeats(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate-key")
        out[key] = value
    return out


def no_fractions(text):
    raise ValueError("not-an-integer")


def ceiling(manifest: dict, capability: str) -> str | None:
    for item in manifest["capabilities"]:
        if item["capability"] == capability and "strength" in item:
            return item["strength"]["rank"]
    return None


def check_run_description(run: dict, manifest: dict, known_inputs: set[str]) -> None:
    """The rules a run description must keep before anything is executed."""
    declared = {t["name"] for t in manifest.get("tools", [])}
    program = run.get("program", {})
    if program.get("tool") not in declared:
        raise Refused("undeclared-tool")
    for path in [program.get("path", "")] + [f.get("path", "") for f in run.get("inputs", []) + run.get("outputs", [])]:
        if pathcheck.check(str(path).encode("utf-8", errors="surrogatepass")) is not None:
            raise Refused("bad-path")
    for item in run.get("inputs", []):
        if item["path"] not in known_inputs:
            raise Refused("input-not-in-key")
    if not isinstance(run.get("args"), list) or not all(isinstance(a, str) and "\x00" not in a for a in run["args"]):
        raise Refused("bad-arguments")


def check_final(final: dict, manifest: dict, capability: str, runs_done: int) -> None:
    """The rules a final answer must keep."""
    if final.get("verdict") not in ("passed", "failed", "error", "unsupported"):
        raise Refused("bad-verdict")
    if final["verdict"] in ("passed", "failed"):
        if runs_done == 0:
            raise Refused("verdict-without-run")
        top, got = ceiling(manifest, capability), final.get("strength", {}).get("rank")
        if got not in RANKS or top is None or RANKS.index(got) > RANKS.index(top):
            raise Refused("strength-above-ceiling")


def drive_check(session: Session, obligation: dict, inputs: list[dict], tools: list[dict], report_for) -> dict:
    """Take one obligation through start, runs and final. `report_for(run_number, description)` returns
    the executor's report for a run, or None if there is none yet, in which case the description is returned."""
    known = {f["path"] for f in inputs}
    body = session.ask("obligation.check", {"op": "start", "obligation": obligation, "inputs": inputs, "tools": tools, "platform": PLATFORM})
    check_id, runs = session.last_request, 0
    while True:
        if ("next" in body) == ("final" in body):
            raise Refused("neither-or-both")
        if "final" in body:
            check_final(body["final"], session.manifest, "obligation.check", runs)
            return {"final": body["final"], "runs": runs}
        check_run_description(body["next"], session.manifest, known)
        report = report_for(runs + 1, body["next"])
        if report is None:
            return {"pending": body["next"]}
        runs += 1
        if report.get("end") != "exited":
            return {"final": {"verdict": "error", "reason": "run-" + str(report.get("end"))}, "runs": runs}
        body = session.ask("obligation.check", {"op": "run.result", "check": check_id, "run": runs, "report": report})


def list_project(session: Session, root: pathlib.Path) -> tuple[list[dict], list[dict]]:
    files = [file_ref(p, root) for p in sorted((root / "spec").glob("*/*")) if p.suffix in (".tla", ".cfg", ".json") and p.is_file()
             and p.name not in ("dump-settings.json",)]
    body = session.ask("obligation.enumerate", {"binding": "kernel-models", "definitions": [], "files": files})
    obligations = [dict(o, binding="kernel-models") for o in body["obligations"]]
    names = [o["name"] for o in obligations]
    if len(names) != len(set(names)):
        raise Refused("duplicate-obligation")
    return obligations, files


def inputs_of(obligation: dict, files: list[dict]) -> list[dict]:
    folder = obligation["config"]["folder"] + "/"
    return [f for f in files if f["path"].startswith(folder) and not f["path"].endswith(".json")]


def collect(args) -> int:
    site = json.loads(args.site.read_text(encoding="utf-8"))
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    transcript: list = []
    tools = [{"name": name, "digest": "sha256:" + "0" * 64} for name in sorted(site["tool_roots"])]
    session = Session([sys.executable, str(ROOT / "providers" / "tlc" / "provider.py")], ROOT, transcript)
    try:
        obligations, files = list_project(session, ROOT)
        pending = []
        for obligation in obligations:
            got = drive_check(session, obligation, inputs_of(obligation, files), tools, lambda n, d: None)
            if "pending" not in got:
                raise Refused("verdict-without-run")
            pending.append({"obligation": obligation, "run": got["pending"]})
    finally:
        session.close()
    work = pathlib.Path(tempfile.mkdtemp(prefix="dodona-collect-"))
    bundle, dest = work / "bundle", work / "fetched"
    shutil.copytree(ROOT / "spec", bundle / "spec", ignore=shutil.ignore_patterns("runs", "*.md", "expected.json"))
    shutil.copy(ROOT / ".github" / "site" / "batch_driver.py", bundle / "batch_driver.py")
    roots = site["tool_roots"]
    cases = []
    for item in pending:
        run = item["run"]
        argv = [f"{roots[run['program']['tool']]}/{run['program']['path']}"]
        for arg in run["args"]:
            for name, where in roots.items():
                arg = arg.replace("${tool:" + name + "}", where)
            argv.append(arg)
        cases.append({"name": item["obligation"]["name"], "cwd": ".", "argv": argv})
    measure = sorted({c["argv"][0] for c in cases} | set(site.get("measure", [])))
    (bundle / "manifest.json").write_text(json.dumps({"out": "out", "cases": cases, "measure": measure}, indent=1), encoding="utf-8")
    values = {"source": str(bundle), "dest": str(dest), "timeout": str(site.get("batch_timeout_seconds", 3600))}
    print(f"sending {len(cases)} runs to the executor as one job", flush=True)
    done = subprocess.run([part.format(**values) for part in site["batch_command"]], capture_output=True, text=True, encoding="utf-8", errors="replace")
    fetched = dest / "out" if (dest / "out").exists() else dest
    reachable = fetched.exists() and any(fetched.glob("*/*.exit"))
    if reachable:
        shutil.copytree(fetched, out / "outputs", dirs_exist_ok=True)
    else:
        print("the executor returned nothing; every run is recorded as unavailable:", (done.stderr or done.stdout)[-300:].strip())
    measured = json.loads((fetched / "measured.json").read_text(encoding="utf-8")) if (fetched / "measured.json").exists() else {}
    (out / "runs.json").write_text(json.dumps({"reachable": reachable, "pending": pending, "measured": measured, "tool_roots": roots,
                                               "executor": site.get("executor_name", "site")}, indent=1) + "\n", encoding="utf-8")
    (out / "transcript-collect.json").write_text(json.dumps(transcript, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"obligations": len(pending), "reachable": reachable}))
    return 0


def kernel(command: list[str], sub: str, payload: dict) -> dict:
    done = subprocess.run(command + [sub], input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=600)
    if done.returncode != 0:
        raise RuntimeError(f"the kernel exited with {done.returncode} on {sub}: {done.stderr.decode('utf-8', 'replace')[-200:]}")
    return json.loads(done.stdout.decode("utf-8"))


def conclude(args) -> int:
    runs = json.loads((args.runs / "runs.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "dodona.lock").read_text(encoding="utf-8"))
    transcript: list = []
    measured = runs["measured"]
    pinned = {t["name"]: t for t in lock["tools"]}
    tools, unpinned, mismatched = [], [], []
    for name, entry in sorted(pinned.items()):
        seen = measured.get(entry["measured_file"])
        tools.append({"name": name, "digest": "sha256:" + (seen or "0" * 64)})
        if entry["sha256"] is None:
            unpinned.append(name)
        elif seen != entry["sha256"]:
            mismatched.append(name)
    session = Session([sys.executable, str(ROOT / "providers" / "tlc" / "provider.py")], ROOT, transcript)
    counts = {"passed": 0, "failed": 0, "error": 0, "unavailable": 0, "unsupported": 0, "refused": 0}
    project = {}
    try:
        obligations, files = list_project(session, ROOT)
        stored = {item["obligation"]["name"]: item for item in runs["pending"]}
        for obligation in obligations:
            name = obligation["name"]
            inputs = inputs_of(obligation, files)
            preimage = {"obligation": canonical.identity({"binding": obligation["binding"], "name": name}), "kind": "check",
                        "inputs": {"specified_by": canonical.sort_set([f["identity"] for f in inputs if f["path"] in obligation["specified_by"]]),
                                   "targets": canonical.sort_set([f["identity"] for f in inputs if f["path"] in obligation["targets"]]),
                                   "closure": canonical.sort_set([f["identity"] for f in inputs]),
                                   "tools": tools, "config": canonical.identity(obligation["config"]), "expect": obligation["expect"]},
                        "provider": {"name": session.manifest["name"], "version": session.manifest["version"], "protocol": session.manifest["protocol"]}}
            project[name] = {"preimage": preimage}

            def report_for(number, description, name=name):
                if not runs["reachable"]:
                    return {"end": "unavailable"}
                if mismatched:
                    return {"end": "tool-mismatch"}
                if name not in stored or stored[name]["run"] != description:
                    raise Refused("run-changed")
                captured = args.runs / "outputs" / f"{name}.txt"
                status = args.runs / "outputs" / f"{name}.exit"
                if not captured.exists() or not status.exists() or status.read_text().strip() == "did-not-start":
                    return {"end": "limit-exceeded"}
                return {"handle": name, "end": "exited", "exit_status": int(status.read_text().strip()), "platform": PLATFORM,
                        "tools_ran": tools, "isolation": "best-effort", "outputs": [],
                        "captured_output": {"path": captured.resolve().relative_to(ROOT).as_posix() if captured.resolve().is_relative_to(ROOT) else str(captured),
                                            "identity": "sha256:" + hashlib.sha256(captured.read_bytes()).hexdigest()}}
            try:
                got = drive_check(session, obligation, inputs, tools, report_for)
            except Refused as err:
                counts["refused"] += 1
                kernel(args.kernel, "ledger-append", {"ledger": str(args.ledger), "kind": "outcome", "wait_ms": 5000,
                                                       "body": {"obligation": name, "verdict": "error", "reason": "provider-" + str(err)}})
                continue
            final = got["final"]
            verdict = "unavailable" if final.get("reason") == "run-unavailable" else final["verdict"]
            counts[verdict] += 1
            if verdict in ("passed", "failed"):
                key = kernel(args.kernel, "key", preimage)["core_key"]
                body = {"obligation": name, "preimage": preimage, "core_key": key, "platform": "linux/aarch64", "verdict": verdict,
                        "writer": args.writer, "strength": final["strength"], "summary": final.get("summary", {}),
                        "executor": runs["executor"], "unpinned_tools": unpinned}
                kernel(args.kernel, "ledger-append", {"ledger": str(args.ledger), "kind": "evidence", "body": body, "wait_ms": 5000})
            else:
                kernel(args.kernel, "ledger-append", {"ledger": str(args.ledger), "kind": "outcome", "wait_ms": 5000,
                                                       "body": {"obligation": name, "verdict": verdict, "reason": final.get("reason", "")}})
    finally:
        session.close()
    (args.runs / "transcript-conclude.json").write_text(json.dumps(transcript, indent=1) + "\n", encoding="utf-8")
    (args.runs / "project-obligations.json").write_text(json.dumps(project, indent=1) + "\n", encoding="utf-8")
    counts.update(unpinned_tools=unpinned, mismatched_tools=mismatched)
    print(json.dumps(counts))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    one = sub.add_parser("collect")
    one.add_argument("--site", type=pathlib.Path, required=True)
    one.add_argument("--out", type=pathlib.Path, required=True)
    two = sub.add_parser("conclude")
    two.add_argument("--runs", type=pathlib.Path, required=True)
    two.add_argument("--ledger", type=pathlib.Path, required=True)
    two.add_argument("--writer", required=True)
    two.add_argument("--kernel", nargs=argparse.REMAINDER, required=True)
    args = ap.parse_args()
    return collect(args) if args.command == "collect" else conclude(args)


if __name__ == "__main__":
    sys.exit(main())
