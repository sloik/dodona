"""Runs a project's checks through a provider, an executor and a kernel.

Stage-0 helper (decision 0026). This is the first time the pieces are joined:
a provider lists obligations and describes the runs it needs, the site's
executor performs them as one job, the provider interprets what came back, and
a kernel writes the results to a ledger and reports status.

It is in two halves, because the executor and the kernel may live on
different machines:

    python tools/host.py plan     --ledger FILE --dumps-from DIR --writer NAME --out PLAN --kernel CMD...
    python tools/host.py collect  --site FILE --out DIR [--plan PLAN] [--dumps]
    python tools/host.py conclude --runs DIR --ledger FILE --writer NAME --kernel CMD...

`plan` reads the ledger kept from earlier runs and asks a kernel which checks
still have a current result; only the others are sent.

`collect` needs the executor. It asks the provider what to run, has it run,
and saves what came back. `conclude` needs a kernel. It gives the provider the
saved results, checks what the provider says against the rules a schema cannot
express, and records the verdicts.

The host enforces: an answer matches its request; every file a provider names is hashed again; each run of a check has its own key; a verdict rests on a run; a
result does not claim more strength than the manifest declares; a program lies
inside a tool the provider declared and the check was given, with the digest
it was given; a result states the class of strength the manifest declares; a
check asks for at most eight runs; every path passes the path check; a run
that did not exit ends the check in error. Every message of a session is kept
in a transcript, so it can be validated against the schemas afterwards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
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
# A provider states how strong its check is by rank; the status report speaks in levels of the assurance scale.
LEVEL_OF_RANK = {"documented": "asserted", "sampled": "sampled", "bounded": "bounded", "exhaustive": "proven"}
PLATFORM = {"os": "linux", "arch": "aarch64", "libc": "gnu"}
# Characters that can start or join a path, or make a program read one: a separator, the parent
# directory, a home directory, an argument file, a variable.
PATHLIKE = re.compile(r"[/\\~@$%]|\.\.|[^\x20-\x7e]")  # look-alikes of / and .. are outside printable ASCII
TOOL_FILE = re.compile(r"\$\{tool:([A-Za-z0-9._-]+)\}/([A-Za-z0-9._/-]+)")
TOOL_NAME = re.compile(r"\$\{tool:([^}]*)\}")  # every mention of a tool in an argument, with or without a file after it
MAX_RUNS = 8  # a check may ask for this many runs and no more


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
        try:
            self.send({"type": "hello", "protocol": ["0.2"], "limits": {"max_line_bytes": 1048576, "deadline_ms": int(deadline_s * 1000)}, "echo": echo})
            answer = self.receive()
            if answer.get("type") != "manifest" or answer.get("echo") != echo:
                raise Refused("bad-manifest")
            self.manifest = answer["manifest"]
        except Refused:
            self.tree.end()  # a session that never opened leaves no provider behind
            raise

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
            data = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        except UnicodeEncodeError:
            raise Refused("encoding") from None  # a lone surrogate the provider sent cannot be passed on
        try:
            self.tree.proc.stdin.write(data)
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
        if depth(message) > 64:
            raise Refused("too-deep")
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


def depth(value) -> int:
    if isinstance(value, dict):
        return 1 + max((depth(v) for v in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((depth(v) for v in value), default=0)
    return 0


def no_repeats(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate-key")
        out[key] = value
    return out


def no_fractions(text):
    raise ValueError("not-an-integer")


def declared_strength(manifest: dict, capability: str) -> dict | None:
    for item in manifest["capabilities"]:
        if item["capability"] == capability and "strength" in item:
            return item["strength"]
    return None


def ceiling(manifest: dict, capability: str) -> str | None:
    strength = declared_strength(manifest, capability)
    return strength["rank"] if strength else None


def run_key(check_key: str, number: int, description: dict) -> str:
    """The key one run of a check is submitted under. It includes the run's number,
    so a second run with the same description is never answered from the first."""
    return canonical.identity({"check": check_key, "run": number, "description": canonical.identity(description)})


def rehash(item: dict, root: pathlib.Path) -> None:
    """A provider's word for what a file contains is never taken: the bytes are hashed again."""
    path = root / item["path"]
    if not path.is_file() or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != item.get("identity"):
        raise Refused("identity-mismatch")


def check_run_description(run: dict, manifest: dict, known_inputs: dict[str, str], known_tools: dict[str, str],
                          platform: dict | None = None, named_files: set[str] | None = None) -> None:
    """The rules a run description must keep before anything is executed.
    `known_tools` gives the digest of each tool the check was given: the ones its result is keyed by.
    `platform` is the platform the check was asked for; `named_files` the files its obligation names."""
    if platform is not None and run.get("platform") != platform:
        raise Refused("platform-mismatch")  # a run must target the platform the check was asked for
    declared = {t["name"] for t in manifest.get("tools", [])}
    program = run.get("program", {})
    named = [program.get("tool")] + [name for a in run.get("args", []) if isinstance(a, str) for name in TOOL_NAME.findall(a)]
    if any(tool not in declared for tool in named):
        raise Refused("undeclared-tool")
    if any(tool not in known_tools for tool in named):
        raise Refused("tool-not-in-key")  # declared, but not among the tools this check was given
    for item in run.get("tools", []):
        if not isinstance(item, dict) or item.get("name") not in known_tools:
            raise Refused("tool-not-in-key")
        if item.get("digest") != known_tools.get(item["name"]):
            raise Refused("tool-digest-mismatch")  # the run would use another tool than the one the result is keyed by
    placed = [m for a in run.get("args", []) if isinstance(a, str) for m in TOOL_FILE.findall(a)]
    for path in ([program.get("path", "")] + [f.get("path", "") for f in run.get("inputs", []) + run.get("outputs", [])]
                 + [path for _, path in placed] + ([run["cwd"]] if "cwd" in run else [])):
        if pathcheck.check(str(path).encode("utf-8", errors="surrogatepass")) is not None:
            raise Refused("bad-path")
    # Arguments by allowlist, not by looking for what is forbidden: that can never be complete.
    # An argument with any character that can start or join a path must be, exactly, one of the
    # run's input files or one file of a declared tool. Anything else is a word: an option, a number.
    inputs = {f.get("path") for f in run.get("inputs", [])}
    for arg in run.get("args", []):
        text = str(arg)
        if text in inputs or TOOL_FILE.fullmatch(text) or "\x00" in text:
            continue  # a NUL byte is refused below, under its own reason
        if PATHLIKE.search(text):
            raise Refused("bad-path")  # an argument may name only the run's own files, and only as a whole argument
    if run.get("env"):
        raise Refused("env-not-allowed")  # a variable can change what a program loads; the stage-0 host allows none
    if {f.get("path") for f in run.get("outputs", [])} & inputs:
        raise Refused("output-overwrites-input")
    for item in run.get("inputs", []):
        if item["path"] not in known_inputs:
            raise Refused("input-not-in-key")
        if known_inputs[item["path"]] is not None and item.get("identity") != known_inputs[item["path"]]:
            raise Refused("identity-mismatch")
    if not isinstance(run.get("args"), list) or not all(isinstance(a, str) and "\x00" not in a for a in run["args"]):
        raise Refused("bad-arguments")
    if named_files is not None and not named_files <= {f.get("path") for f in run.get("inputs", [])}:
        raise Refused("missing-input")  # a run must be given every file its obligation names


def check_final(final: dict, manifest: dict, capability: str, runs_done: int, root: pathlib.Path = ROOT) -> None:
    """The rules a final answer must keep."""
    for item in final.get("attachments", []):
        if pathcheck.check(str(item.get("path", "")).encode("utf-8", errors="surrogatepass")) is not None:
            raise Refused("bad-path")
        rehash(item, root)
    if final.get("verdict") not in ("passed", "failed", "error", "unsupported"):
        raise Refused("bad-verdict")
    if final["verdict"] in ("passed", "failed"):
        if runs_done == 0:
            raise Refused("verdict-without-run")
        top, got = ceiling(manifest, capability), final.get("strength", {}).get("rank")
        if got not in RANKS or top is None or RANKS.index(got) > RANKS.index(top):
            raise Refused("strength-above-ceiling")
        if final["strength"].get("class") != declared_strength(manifest, capability).get("class"):
            raise Refused("strength-class-mismatch")  # a test is not a proof, whatever its rank


def drive_check(session: Session, obligation: dict, inputs: list[dict], tools: list[dict], report_for) -> dict:
    """Take one obligation through start, runs and final. `report_for(run_number, description)` returns
    the executor's report for a run, or None if there is none yet, in which case the description is returned."""
    known = {f["path"]: f["identity"] for f in inputs}
    if not set(obligation.get("specified_by", []) + obligation.get("targets", [])) <= set(known):
        raise Refused("unknown-file")  # an obligation names a file the check was not given
    known_tools = {t["name"]: t["digest"] for t in tools}
    check_key = canonical.identity({"obligation": obligation, "inputs": inputs})
    keys: list[str] = []
    body = session.ask("obligation.check", {"op": "start", "obligation": obligation, "inputs": inputs, "tools": tools, "platform": PLATFORM})
    check_id, runs = session.last_request, 0
    while True:
        if ("next" in body) == ("final" in body):
            raise Refused("neither-or-both")
        if "final" in body:
            check_final(body["final"], session.manifest, "obligation.check", runs)
            return {"final": body["final"], "runs": runs, "run_keys": keys}
        if runs >= MAX_RUNS:
            raise Refused("too-many-runs")  # refused when the next run is asked for, before it starts
        check_run_description(body["next"], session.manifest, known, known_tools, PLATFORM,
                              set(obligation.get("specified_by", []) + obligation.get("targets", [])))
        keys.append(run_key(check_key, runs + 1, body["next"]))
        report = report_for(runs + 1, body["next"])
        if report is None:
            return {"pending": body["next"], "run_key": keys[-1]}
        runs += 1
        if report.get("end") != "exited":
            return {"final": {"verdict": "error", "reason": "run-" + str(report.get("end"))}, "runs": runs}
        body = session.ask("obligation.check", {"op": "run.result", "check": check_id, "run": runs, "report": report})


# What the provider said it could not make into a check, last time it was asked. A run is not
# green while this is not empty: a case that cannot be checked is not a case that passed.
REFUSED_BY_PROVIDER: list[str] = []


def list_project(session: Session, root: pathlib.Path) -> tuple[list[dict], list[dict]]:
    files = [file_ref(p, root) for p in sorted((root / "spec").glob("*/*")) if p.suffix in (".tla", ".cfg", ".json") and p.is_file()
             and p.name not in ("dump-settings.json",)]
    body = session.ask("obligation.enumerate", {"binding": "kernel-models", "definitions": [], "files": files})
    obligations = [dict(o, binding="kernel-models") for o in body["obligations"]]
    REFUSED_BY_PROVIDER[:] = sorted(r.get("name", "?") for r in body.get("rejected", []))
    names = [o["name"] for o in obligations]
    if len(names) != len(set(names)):
        raise Refused("duplicate-obligation")
    return obligations, files


def lock_tools() -> tuple[list[dict], dict]:
    """The tools as this site's pins give them (not yet a lock: decision 0026). A tool that is not pinned yet has a digest of zeros,
    which no measurement can equal, so nothing recorded in that state counts later."""
    lock = json.loads((ROOT / ".github" / "site" / "pins.json").read_text(encoding="utf-8"))
    pinned = {t["name"]: t for t in lock["tools"]}
    return [{"name": n, "version": pinned[n]["version"], "digest": "sha256:" + (pinned[n]["sha256"] or "0" * 64)} for n in sorted(pinned)], pinned


def preimage(obligation: dict, inputs: list[dict], tools: list[dict], manifest: dict) -> dict:
    """The inputs a result depends on (conformance/vectors/core-key.json)."""
    return {"obligation": canonical.identity({"binding": obligation["binding"], "name": obligation["name"]}), "kind": "check",
            "inputs": {"specified_by": canonical.sort_set([f["identity"] for f in inputs if f["path"] in obligation["specified_by"]]),
                       "targets": canonical.sort_set([f["identity"] for f in inputs if f["path"] in obligation["targets"]]),
                       # A file is its name and its content: renaming or swapping two files is a change.
                       "closure": canonical.sort_set([canonical.identity({"path": f["path"], "identity": f["identity"]}) for f in inputs]),
                       "tools": [{"name": t["name"], "digest": t["digest"]} for t in tools], "config": canonical.identity(obligation["config"]), "expect": obligation["expect"]},
            # The version a provider states is its word; its code is what ran. Both are in the key.
            "provider": {"name": manifest["name"], "version": f"{manifest['version']}+{provider_code()}+{runner_code()}", "protocol": manifest["protocol"]}}


def runner_code() -> str:
    """A digest of the code that sends runs and judges what a provider says: a change to its rules makes earlier
    results stop counting, as a change to the provider does."""
    files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("tools/host.py", ".github/site/batch_driver.py")}
    return canonical.identity(files)[len("sha256:"):][:16]


def provider_code() -> str:
    """A digest of every file of the provider, so a change to its code makes its results stop counting."""
    folder = ROOT / "providers" / "tlc"
    files = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(folder.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
    return canonical.identity(files)[len("sha256:"):][:16]


def inputs_of(obligation: dict, files: list[dict]) -> list[dict]:
    folder = obligation["config"]["folder"] + "/"
    return [f for f in files if f["path"].startswith(folder) and not f["path"].endswith(".json")]


def collect(args) -> int:
    site = json.loads(args.site.read_text(encoding="utf-8"))
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    transcript: list = []
    where = site["tool_files"]
    tools, _ = lock_tools()
    chosen = json.loads(args.plan.read_text(encoding="utf-8")) if args.plan else None
    session = Session([sys.executable, str(ROOT / "providers" / "tlc" / "provider.py")], ROOT, transcript)
    try:
        obligations, files = list_project(session, ROOT)
        if chosen is not None:
            obligations = [o for o in obligations if o["name"] in set(chosen["run"])]
        pending = []
        for obligation in obligations:
            got = drive_check(session, obligation, inputs_of(obligation, files), tools, lambda n, d: None)
            if "pending" not in got:
                raise Refused("verdict-without-run")
            pending.append({"obligation": obligation, "run": got["pending"], "run_key": got["run_key"]})
    finally:
        session.close()
    bundle = pathlib.Path(tempfile.mkdtemp(prefix="dodona-collect-")) / "bundle"
    shutil.copytree(ROOT / "spec", bundle / "spec", ignore=shutil.ignore_patterns("runs", "*.md", "expected.json"))
    shutil.copy(ROOT / ".github" / "site" / "batch_driver.py", bundle / "batch_driver.py")
    cases = []
    for item in pending:
        run = item["run"]
        try:
            argv = [where[f"{run['program']['tool']}/{run['program']['path']}"]]
            argv += [TOOL_FILE.sub(lambda m: where[f"{m.group(1)}/{m.group(2)}"], arg) for arg in run["args"]]
        except KeyError as err:
            raise SystemExit(f"this site has no file for {err}; add it to tool_files") from None
        cases.append({"name": item["obligation"]["name"], "cwd": run.get("cwd", "."), "argv": argv})
    if args.dumps:
        # Not obligations yet: two models also write out every state they reach, for tools/check_states.py.
        for config in sorted(ROOT.glob("spec/*/dump.cfg")):
            if chosen is not None and config.parent.name not in chosen["dumps_run"]:
                continue
            folder = config.parent.relative_to(ROOT).as_posix()
            cases.append({"name": f"{config.parent.name}/dump", "cwd": folder, "keep": ["states.dump"],
                          "argv": [where["java/bin/java"], "-cp", where["tla2tools/tla2tools.jar"], "tlc2.TLC"] + DUMP_ARGS})
    if not cases:
        # Everything has a current result. Nothing is sent, and nothing new will be recorded.
        print("nothing to run: every check has a current result")
        job = {"reachable": True, "complete": True, "exit": None, "measured": {}, "fetched": None}
    else:
        job = send_job(site, bundle, cases)
    reachable, complete, measured = job["reachable"], job["complete"], job["measured"]
    if reachable and job["fetched"] is not None:
        shutil.copytree(job["fetched"], out / "outputs", dirs_exist_ok=True)
    (out / "runs.json").write_text(json.dumps({"reachable": reachable, "complete": complete, "queue_exit": job["exit"], "sent": len(cases), "plan": chosen, "pending": pending, "measured": measured,
                                               "executor": site.get("executor_name", "site")}, indent=1) + "\n", encoding="utf-8")
    (out / "transcript-collect.json").write_text(json.dumps(transcript, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"obligations": len(pending), "reachable": reachable, "complete": complete}))
    return 0


def send_job(site: dict, bundle: pathlib.Path, cases: list[dict]) -> dict:
    """Send cases to the site's executor as one job. The only place a job is sent from.

    A job counts as complete only if the executor's own client says it ended
    well AND the driver's end marker lists exactly the cases that were sent.
    Either alone is not enough: a queue can stop a job after its files are
    written, and files can be left by a job that was stopped.
    """
    where = site["tool_files"]
    dest = bundle.parent / "fetched"
    shutil.copy(ROOT / ".github" / "site" / "batch_driver.py", bundle / "batch_driver.py")
    (bundle / "manifest.json").write_text(json.dumps({"out": "out", "cases": cases, "measure": sorted(set(where.values()))}, indent=1), encoding="utf-8")
    values = {"source": str(bundle), "dest": str(dest), "timeout": str(site.get("batch_timeout_seconds", 3600))}
    print(f"sending {len(cases)} runs to the executor as one job", flush=True)
    try:
        done = subprocess.run([part.format(**values) for part in site["batch_command"]], capture_output=True, text=True, encoding="utf-8", errors="replace")
        code, said = done.returncode, (done.stderr or done.stdout)[-300:].strip()
    except OSError as err:
        code, said = None, str(err)
    fetched = dest / "out" if (dest / "out").exists() else dest
    reachable = fetched.exists() and any(fetched.glob("*/*.exit"))
    if not reachable:
        print("the executor returned nothing:", said)
    seen = json.loads((fetched / "measured.json").read_text(encoding="utf-8")) if (fetched / "measured.json").exists() else {}
    marker = fetched / "complete.json"
    marked = marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("cases") == [c["name"] for c in cases]
    complete = bool(reachable and code == 0 and marked)
    if reachable and not complete:
        print(f"the job did not end well (the executor's client exited with {code}; end marker {'present' if marked else 'missing'}); "
              "nothing from it will be taken as a result")
    return {"reachable": bool(reachable), "complete": complete, "exit": code, "fetched": fetched,
            "measured": {name: seen.get(path) for name, path in where.items()}}


def job_fault(runs: dict) -> str | None:
    """Why nothing from this job may be judged, measured against this site's pins; None if it may."""
    _, pinned = lock_tools()
    measured = runs.get("measured", {})
    unmeasured = [n for n in sorted(pinned) if not measured.get(pinned[n]["file"])]
    mismatched = [n for n in sorted(pinned) if pinned[n]["sha256"] is not None and measured.get(pinned[n]["file"]) != pinned[n]["sha256"]]
    return proves_nothing(runs, unmeasured, mismatched)


def proves_nothing(runs: dict, unmeasured: list, mismatched: list) -> str | None:
    """Why no run of this job may become a verdict, or None if the job can be read."""
    if not runs.get("reachable"):
        return "unavailable"
    if not runs.get("complete"):
        return "job-incomplete"  # a job stopped part of the way proves nothing, whatever it left behind
    if unmeasured:
        return "tool-unmeasured"  # never to be confused with a tool that is merely not pinned
    if mismatched:
        return "tool-mismatch"
    return None


def kernel(command: list[str], sub: str, payload: dict) -> dict:
    done = subprocess.run(command + [sub], input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=600)
    if done.returncode != 0:
        raise RuntimeError(f"the kernel exited with {done.returncode} on {sub}: {done.stderr.decode('utf-8', 'replace')[-200:]}")
    return json.loads(done.stdout.decode("utf-8"))


# How a dump model is run. Part of what a list of states depends on.
DUMP_ARGS = ["-workers", "1", "-config", "dump.cfg", "-dump", "states", "MCDump.tla"]


def dump_key(model_dir: pathlib.Path) -> str:
    """What a list of states written out by a dump model depends on: its files, how it is run, the pinned tools,
    and the code that runs it."""
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(model_dir.iterdir()) if p.suffix in (".tla", ".cfg")}
    return canonical.identity({"files": files, "args": DUMP_ARGS, "tools": lock_tools()[0], "runner": runner_code()})


def plan(args) -> int:
    """Decide what must run, from the ledger kept from earlier runs. The kernel decides; this only asks.

    An obligation is reused when the kernel reports it passed or failed from records that count:
    written by this writer, on this platform, under the key of the inputs as they are now. Anything
    else (never run, an error, a conflict, a record under an old key) runs again.
    """
    import status as status_tool  # the same scenario the status report is worked out from
    entries = status_tool.read_ledgers([args.ledger] if args.ledger.exists() else [], args.kernel)
    if entries is None:
        print("the kept ledger is damaged; everything runs again")
        entries = []
    policy, _ = status_tool.anchored_policy(args.policy_ref)
    asked = status_tool.scenario([e for e in entries if e.get("kind") == "evidence"], args.writer, policy)
    report = kernel(args.kernel, "scenario", asked)["results"][-1] if asked["steps"] else {"obligations": {}}
    current = sorted(n for n, o in report["obligations"].items() if o["status"] in ("passed", "failed"))
    every = sorted(asked["obligations"])
    dumps_kept = json.loads((args.dumps_from / "dumps.json").read_text(encoding="utf-8")) if (args.dumps_from / "dumps.json").exists() else {}
    dumps = {d.parent.name: dump_key(d.parent) for d in sorted(ROOT.glob("spec/*/dump.cfg"))}
    session = Session([sys.executable, str(ROOT / "providers" / "tlc" / "provider.py")], ROOT, [])
    try:
        list_project(session, ROOT)
    finally:
        session.close()
    chosen = {"run": [n for n in every if n not in current], "reuse": current, "ledger_entries": len(entries),
              "refused_by_provider": list(REFUSED_BY_PROVIDER),
              "dumps_run": sorted(m for m, k in dumps.items() if dumps_kept.get(m) != k or not (args.dumps_from / m / "dump.states.dump").exists()),
              "dumps_reuse": sorted(m for m, k in dumps.items() if dumps_kept.get(m) == k and (args.dumps_from / m / "dump.states.dump").exists()),
              "dump_keys": dumps}
    args.out.write_text(json.dumps(chosen, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"run": len(chosen["run"]), "reuse": len(chosen["reuse"]), "dumps_run": chosen["dumps_run"], "dumps_reuse": chosen["dumps_reuse"]}))
    return 0


def conclude(args) -> int:
    if not args.runs.resolve().is_relative_to(ROOT):
        raise SystemExit("the saved runs must be inside the project directory, where the provider can read them by relative path")
    runs = json.loads((args.runs / "runs.json").read_text(encoding="utf-8"))
    transcript: list = []
    tools, pinned = lock_tools()
    measured = runs["measured"]
    unmeasured = [n for n in sorted(pinned) if not measured.get(pinned[n]["file"])]
    ran = [{"name": n, "digest": "sha256:" + (measured.get(pinned[n]["file"]) or "0" * 64)} for n in sorted(pinned)]
    unpinned = [n for n in sorted(pinned) if pinned[n]["sha256"] is None]
    mismatched = [n for n in sorted(pinned) if pinned[n]["sha256"] is not None and measured.get(pinned[n]["file"]) != pinned[n]["sha256"]]
    session = Session([sys.executable, str(ROOT / "providers" / "tlc" / "provider.py")], ROOT, transcript)
    counts = {"passed": 0, "failed": 0, "error": 0, "unavailable": 0, "unsupported": 0, "refused": 0, "reused": 0}
    try:
        obligations, files = list_project(session, ROOT)
        stored = {item["obligation"]["name"]: item for item in runs["pending"]}
        reused = set((runs.get("plan") or {}).get("reuse", []))
        for obligation in obligations:
            name = obligation["name"]
            if name in reused:
                counts["reused"] += 1  # its record from an earlier run still counts; nothing new is written
                continue
            inputs = inputs_of(obligation, files)
            # The key is made from what was measured to have run, so a result made with a tool
            # the lock does not pin can never be taken for one made with the pinned tool.
            made_with = preimage(obligation, inputs, ran, session.manifest)

            def report_for(number, description, name=name):
                nothing = proves_nothing(runs, unmeasured, mismatched)
                if nothing:
                    return {"end": nothing}
                if name not in stored or stored[name]["run"] != description:
                    raise Refused("run-changed")
                expected = run_key(canonical.identity({"obligation": obligation, "inputs": inputs}), number, description)
                if stored[name].get("run_key") != expected:
                    raise Refused("run-key-mismatch")  # what was executed was not submitted for this run of this check
                captured = args.runs / "outputs" / f"{name}.txt"
                status = args.runs / "outputs" / f"{name}.exit"
                if not captured.exists() or not status.exists() or status.read_text().strip() == "did-not-start":
                    return {"end": "no-output"}
                return {"handle": name, "end": "exited", "exit_status": int(status.read_text().strip()), "platform": PLATFORM,
                        "tools_ran": ran, "isolation": "best-effort", "outputs": [],
                        "captured_output": {"path": captured.resolve().relative_to(ROOT).as_posix(),
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
                key = kernel(args.kernel, "key", made_with)["core_key"]
                body = {"obligation": name, "preimage": made_with, "core_key": key, "platform": "linux/aarch64", "verdict": verdict,
                        "writer": args.writer, "level": LEVEL_OF_RANK.get(final["strength"]["rank"], "asserted"), "strength": final["strength"], "summary": final.get("summary", {}),
                        "executor": runs["executor"], "unpinned_tools": unpinned}
                kernel(args.kernel, "ledger-append", {"ledger": str(args.ledger), "kind": "evidence", "body": body, "wait_ms": 5000})
            else:
                kernel(args.kernel, "ledger-append", {"ledger": str(args.ledger), "kind": "outcome", "wait_ms": 5000,
                                                       "body": {"obligation": name, "verdict": verdict, "reason": final.get("reason", "")}})
    finally:
        session.close()
    (args.runs / "transcript-conclude.json").write_text(json.dumps(transcript, indent=1) + "\n", encoding="utf-8")
    counts.update(unpinned_tools=unpinned, mismatched_tools=mismatched, unmeasured_tools=unmeasured, job_complete=bool(runs.get("complete")))
    print(json.dumps(counts))
    return 0


def check(args) -> int:
    """One obligation through a provider, each run sent to an executor command: the host rules on their own.

    Reads {"root", "provider", "obligation", "inputs", "tools", "platform", "executor", "deadline_ms"} on
    standard input and prints {"outcome": "verdict", "verdict": V} or {"outcome": "refused", "reason": R}
    (conformance/README.md, "Host checks"). The reference for tools/run_check_cases.py.
    """
    global PLATFORM
    asked = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    root = pathlib.Path(asked["root"]).resolve()
    PLATFORM = asked["platform"]
    check_key = canonical.identity({"obligation": asked["obligation"], "inputs": asked["inputs"]})

    def report_for(number, description):
        given = {"number": number, "run_key": run_key(check_key, number, description), "run": description}
        try:
            done = subprocess.run(asked["executor"], input=json.dumps(given).encode("utf-8"), capture_output=True, timeout=600)
            report = json.loads(done.stdout.decode("utf-8"))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return {"end": "executor-failed"}
        return report if done.returncode == 0 and isinstance(report, dict) else {"end": "executor-failed"}

    session = None
    try:
        session = Session(asked["provider"], root, [], deadline_s=asked.get("deadline_ms", 60000) / 1000)
        final = drive_check(session, asked["obligation"], asked["inputs"], asked["tools"], report_for)["final"]
        verdict = "unavailable" if final.get("reason") == "run-unavailable" else final["verdict"]
        answer = {"outcome": "verdict", "verdict": verdict}
    except Refused as err:
        answer = {"outcome": "refused", "reason": str(err)}
    finally:
        if session is not None:
            session.close()
    print(json.dumps(answer))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    one = sub.add_parser("collect")
    one.add_argument("--site", type=pathlib.Path, required=True)
    one.add_argument("--out", type=pathlib.Path, required=True)
    one.add_argument("--dumps", action="store_true", help="also have each model that has a dump.cfg write out its states")
    one.add_argument("--plan", type=pathlib.Path, help="run only what this plan says has no current result")
    three = sub.add_parser("plan")
    three.add_argument("--ledger", type=pathlib.Path, required=True, help="the ledger kept from earlier runs; may be absent")
    three.add_argument("--dumps-from", type=pathlib.Path, required=True, help="where lists of states kept from earlier runs are")
    three.add_argument("--writer", required=True)
    three.add_argument("--out", type=pathlib.Path, required=True)
    three.add_argument("--policy-ref", default="origin/main")
    three.add_argument("--kernel", nargs=argparse.REMAINDER, required=True)
    two = sub.add_parser("conclude")
    two.add_argument("--runs", type=pathlib.Path, required=True)
    two.add_argument("--ledger", type=pathlib.Path, required=True)
    two.add_argument("--writer", required=True)
    two.add_argument("--kernel", nargs=argparse.REMAINDER, required=True)
    sub.add_parser("check", help="one obligation through a provider, runs sent to an executor command; reads JSON on standard input")
    args = ap.parse_args()
    return {"collect": collect, "conclude": conclude, "plan": plan, "check": check}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
