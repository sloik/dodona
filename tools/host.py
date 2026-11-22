"""Runs a project's checks through a provider, an executor and a kernel.

Stage-0 helper (decision 0026). This is the first time the pieces are joined:
a provider lists obligations and describes the runs it needs, the site's
executor performs them as one job, the provider interprets what came back, and
a kernel writes the results to a ledger and reports status.

It is in two halves, because the executor and the kernel may live on
different machines:

    python tools/host.py plan     --ledger FILE --dumps-from DIR --writer NAME --out PLAN [--policy-ref REF] --kernel CMD...
    python tools/host.py collect  --site FILE --out DIR [--plan PLAN] [--dumps]
    python tools/host.py conclude --runs DIR --ledger FILE --writer NAME --kernel CMD...

and, as the reference a kernel's `check` command is judged against (decision 0033):

    python tools/host.py check    < INPUT.json

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
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

# An integer of any length is read whole, so that a long one is not-an-integer, never refused as malformed.
if hasattr(sys, "set_int_max_str_digits"):
    sys.set_int_max_str_digits(0)
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

    def __init__(self, argv: list[str], cwd: pathlib.Path, transcript: list, deadline_s: float = 60, deadline_ms: int | None = None):
        import queue
        import threading
        self.tree = provider_host.Tree(argv) if cwd == pathlib.Path.cwd() else self._start(argv, cwd)
        self.lines: "queue.Queue" = queue.Queue()
        # The deadline as given, in whole milliseconds, is what hello and every request carry; never rounded.
        self.deadline_ms = deadline_ms if deadline_ms is not None else int(deadline_s * 1000)
        deadline_s = self.deadline_ms / 1000
        self.transcript, self.deadline_s, self.next_id = transcript, deadline_s, 0
        log = {"bytes": 0, "kept": b"", "truncated": False}
        threading.Thread(target=provider_host.read_lines, args=(self.tree.proc.stdout, 1048576, self.lines), daemon=True).start()
        threading.Thread(target=provider_host.drain, args=(self.tree.proc.stderr, 65536, log), daemon=True).start()
        echo = "héllo ☃ \u0001\u001f end"
        try:
            self.send({"type": "hello", "protocol": ["0.2"], "limits": {"max_line_bytes": 1048576, "deadline_ms": self.deadline_ms}, "echo": echo})
            answer = self.receive()
            if answer.get("type") != "manifest" or answer.get("echo") != echo:
                raise Refused("bad-manifest")
            self.manifest = answer.get("manifest")
            if not manifest_has_its_shape(self.manifest):
                raise Refused("bad-manifest")
        except Refused:
            self.close()  # shutdown is sent at the end of every session, and no provider is left behind
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
        import threading
        failed: list = []

        def write():
            try:
                self.tree.proc.stdin.write(data)
                self.tree.proc.stdin.flush()
            except (OSError, ValueError):
                failed.append(True)
        writer = threading.Thread(target=write, daemon=True)
        writer.start()
        writer.join(self.deadline_s)
        if writer.is_alive():
            raise Refused("deadline")  # a provider that stops reading cannot hold the host past the deadline
        if failed:
            raise Refused("closed")

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
        message = strict_load(raw)
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            raise Refused("malformed")
        self.transcript.append({"to": "kernel", "message": message})
        return message

    def ask(self, capability: str, body: dict) -> dict:
        """Send one request and return the body of its result."""
        self.next_id += 1
        ident = str(self.next_id)
        self.send({"type": "request", "id": ident, "deadline_ms": self.deadline_ms, "capability": capability, "body": body})
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
            self.tree.proc.wait(timeout=1)  # a provider is given a moment to exit on its own
        except (Refused, subprocess.TimeoutExpired):
            pass
        self.tree.end()


def depth(value) -> int:
    """How deep objects and lists nest, without recursion, so no depth crashes the reader."""
    deepest, todo = 0, [(value, 0)]
    while todo:
        here, level = todo.pop()
        if isinstance(here, (dict, list)):
            level += 1
            deepest = max(deepest, level)
            todo.extend((v, level) for v in (here.values() if isinstance(here, dict) else here))
    return deepest


def no_repeats(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate-key")
        out[key] = value
    return out


def no_fractions(text):
    raise ValueError("not-an-integer")


def safe_integer(text):
    value = int(text)
    if abs(value) > 2 ** 53 - 1:
        raise ValueError("not-an-integer")  # beyond this, a number cannot be read the same everywhere
    return value


def half_pair(value) -> bool:
    """Whether a string anywhere in the value holds half of a UTF-16 pair. Without recursion."""
    todo = [value]
    while todo:
        here = todo.pop()
        if isinstance(here, str):
            if any(0xD800 <= ord(c) <= 0xDFFF for c in here):
                return True
        elif isinstance(here, dict):
            todo.extend(here.keys())
            todo.extend(here.values())
        elif isinstance(here, list):
            todo.extend(here)
    return False


def not_json(text):
    raise ValueError("malformed")  # NaN and Infinity are not JSON, whatever Python's reader allows


def strict_load(raw: bytes, limit: int | None = 64):
    """Read one JSON text as the canonical encoding writes it, or raise Refused with the reason. Nesting deeper
    than `limit` is `too-deep`; with no limit, only what the reader cannot hold is."""
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_repeats, parse_float=no_fractions, parse_int=safe_integer,
                           parse_constant=not_json)
    except UnicodeDecodeError:
        raise Refused("encoding") from None
    except RecursionError:
        raise Refused("too-deep") from None  # nested beyond what the reader can hold, so far beyond 64
    except ValueError as err:
        raise Refused(str(err) if str(err) in ("duplicate-key", "not-an-integer") else "malformed") from None
    if half_pair(value):
        raise Refused("encoding")
    if limit is not None and depth(value) > limit:
        raise Refused("too-deep")
    return value


TOOL_NAME_TEXT = re.compile(r"[A-Za-z0-9._-]+")


def manifest_has_its_shape(manifest) -> bool:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("capabilities"), list):
        return False
    names = []
    for item in manifest["capabilities"]:
        if not isinstance(item, dict) or not isinstance(item.get("capability"), str):
            return False
        names.append(item["capability"])
        strength = item.get("strength")
        if item["capability"] == "obligation.check" and "strength" in item:  # given as null is given
            if not isinstance(strength, dict) or not isinstance(strength.get("class"), str) or strength.get("rank") not in RANKS:
                return False
    if len(names) != len(set(names)):
        return False
    tools = manifest.get("tools")  # a manifest without a list of tools is not read as declaring none
    return isinstance(tools, list) and all(isinstance(t, dict) and isinstance(t.get("name"), str) and TOOL_NAME_TEXT.fullmatch(t["name"]) for t in tools)


def description_has_its_shape(run) -> bool:
    def objects(value, *fields):
        return isinstance(value, list) and all(isinstance(v, dict) and all(isinstance(v.get(f), str) for f in fields) for v in value)
    if not isinstance(run, dict):
        return False
    program = run.get("program")
    return (isinstance(program, dict) and isinstance(program.get("tool"), str) and isinstance(program.get("path"), str)
            and isinstance(run.get("args"), list) and objects(run.get("inputs"), "path", "identity") and objects(run.get("outputs"), "path")
            and objects(run.get("tools"), "name", "digest") and isinstance(run.get("platform"), dict)
            and ("cwd" not in run or isinstance(run["cwd"], str))
            and ("limits" not in run or (isinstance(run["limits"], dict) and all(type(v) is int for v in run["limits"].values()))))


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


def plain_file(root: pathlib.Path, relative: str) -> bool:
    """A regular file of at most 64 MiB, reached from root without following a link at any step."""
    import os
    import stat
    here = root
    for part in relative.split("/"):
        here = here / part
        try:
            mode = os.lstat(here).st_mode
        except OSError:
            return False
        if stat.S_ISLNK(mode):
            return False
    info = os.lstat(here)
    return stat.S_ISREG(info.st_mode) and info.st_size <= 64 * 1024 * 1024


def rehash(item: dict, root: pathlib.Path) -> None:
    """A provider's word for what a file contains is never taken: the bytes are hashed again."""
    path = root / item["path"]
    if not path.is_file() or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != item.get("identity"):
        raise Refused("identity-mismatch")


def ascii_lower(text: str) -> str:
    """Lower-case ASCII letters only: rule 8 folds no other case."""
    return text.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


def check_run_description(run: dict, manifest: dict, known_inputs: dict[str, str], known_tools: dict[str, str],
                          platform: dict | None = None, named_files: set[str] | None = None) -> None:
    """The rules a run description must keep before anything is executed.
    `known_tools` gives the digest of each tool the check was given: the ones its result is keyed by.
    `platform` is the platform the check was asked for; `named_files` the files its obligation names."""
    if not description_has_its_shape(run):
        raise Refused("bad-description")
    if platform is not None and run.get("platform") != platform:
        raise Refused("platform-mismatch")  # a run must target the platform the check was asked for
    declared = {t["name"] for t in manifest.get("tools", [])}
    program = run.get("program", {})
    named = [program.get("tool")] + [name for a in run.get("args", []) if isinstance(a, str) for name in TOOL_NAME.findall(a)]
    if any(tool not in declared for tool in named):
        raise Refused("undeclared-tool")
    if any(tool not in known_tools for tool in named):
        raise Refused("tool-not-in-key")  # declared, but not among the tools this check was given
    if any(tool not in {t.get("name") for t in run.get("tools", [])} for tool in named):
        raise Refused("tool-not-in-run")  # a tool the run uses is pinned in its own tools, or its digest is never checked
    # Each rule is checked over every entry before the next rule.
    if any(not isinstance(item, dict) or item.get("name") not in known_tools for item in run.get("tools", [])):
        raise Refused("tool-not-in-key")
    if any(item.get("digest") != known_tools.get(item["name"]) for item in run.get("tools", [])):
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
    if "env" in run:
        raise Refused("env-not-allowed")  # a variable can change what a program loads; any env field is refused, whatever its value
    taken = {ascii_lower(p) for p in inputs | set(known_inputs)}
    if any(ascii_lower(f["path"]) in taken for f in run["outputs"]):
        raise Refused("output-overwrites-input")  # compared without regard to case: a disk may ignore it
    if any(item["path"] not in known_inputs for item in run.get("inputs", [])):
        raise Refused("input-not-in-key")
    if any(known_inputs[item["path"]] is not None and item.get("identity") != known_inputs[item["path"]] for item in run.get("inputs", [])):
        raise Refused("identity-mismatch")
    if not isinstance(run.get("args"), list) or not all(isinstance(a, str) and "\x00" not in a for a in run["args"]):
        raise Refused("bad-arguments")
    if named_files is not None and not named_files <= {f.get("path") for f in run.get("inputs", [])}:
        raise Refused("missing-input")  # a run must be given every file its obligation names


def check_final(final: dict, manifest: dict, capability: str, runs_done: int, root: pathlib.Path = ROOT) -> None:
    """The rules a final answer must keep."""
    if not isinstance(final, dict):
        raise Refused("bad-final")
    attachments = final.get("attachments", [])
    if not isinstance(attachments, list) or not all(isinstance(a, dict) and isinstance(a.get("path"), str) and isinstance(a.get("identity"), str) for a in attachments):
        raise Refused("bad-final")
    # Each rule is checked over every attachment before the next rule.
    for item in attachments:
        if pathcheck.check(item["path"].encode("utf-8", errors="surrogatepass")) is not None or not plain_file(root, item["path"]):
            raise Refused("bad-path")
    for item in attachments:
        rehash(item, root)
    if final.get("verdict") not in ("passed", "failed", "error", "unsupported"):
        raise Refused("bad-verdict")
    if final["verdict"] in ("passed", "failed"):
        if runs_done == 0:
            raise Refused("verdict-without-run")
        strength = final.get("strength")
        top, got = ceiling(manifest, capability), strength.get("rank") if isinstance(strength, dict) else None
        if got not in RANKS or top is None or RANKS.index(got) > RANKS.index(top):
            raise Refused("strength-above-ceiling")
        if final["strength"].get("class") != declared_strength(manifest, capability).get("class"):
            raise Refused("strength-class-mismatch")  # a test is not a proof, whatever its rank


def check_steps(session: Session, obligation: dict, inputs: list[dict], tools: list[dict], platform: dict, root: pathlib.Path = ROOT):
    """Take one obligation through start, runs and final, one run at a time: a generator that yields
    `(number, description, run_key)` for each run it needs and is sent the executor's report for it, and returns
    `{"final", "runs", "run_keys"}` (with `"unavailable": True` when the executor said so). Refused as the host
    checks say. Several of these can be advanced side by side, so that their runs go to the executor together."""
    known = {f["path"]: f["identity"] for f in inputs}
    if not set(obligation.get("specified_by", []) + obligation.get("targets", [])) <= set(known):
        raise Refused("unknown-file")  # an obligation names a file the check was not given
    known_tools = {t["name"]: t["digest"] for t in tools}
    check_key = canonical.identity({"obligation": obligation, "inputs": inputs})
    keys: list[str] = []
    body = session.ask("obligation.check", {"op": "start", "obligation": obligation, "inputs": inputs, "tools": tools, "platform": platform})
    check_id, runs = session.last_request, 0
    while True:
        if ("next" in body) == ("final" in body):
            raise Refused("neither-or-both")
        if "final" in body:
            check_final(body["final"], session.manifest, "obligation.check", runs, root)
            return {"final": body["final"], "runs": runs, "run_keys": keys}
        if runs >= MAX_RUNS:
            raise Refused("too-many-runs")  # refused when the next run is asked for, before it starts
        if not description_has_its_shape(body["next"]):
            raise Refused("bad-description")
        check_run_description(body["next"], session.manifest, known, known_tools, platform,
                              set(obligation.get("specified_by", []) + obligation.get("targets", [])))
        keys.append(run_key(check_key, runs + 1, body["next"]))
        report = yield (runs + 1, body["next"], keys[-1])
        runs += 1
        if report.get("end") != "exited":
            # Only the executor's report makes a check unavailable, so the mark is kept outside the final,
            # where nothing a provider says can set it.
            return {"final": {"verdict": "error", "reason": "run-" + str(report.get("end"))}, "runs": runs, "run_keys": keys,
                    "unavailable": report.get("end") == "unavailable"}
        # What the executor says ran must be what was asked for: another platform or another tool is an
        # error, never a result (protocol/messages.schema.json, run_report).
        # Compared as JSON text, so that names of any type sort without failing.
        asked_tools = sorted(json.dumps([t.get("name"), t.get("digest")]) for t in body["next"].get("tools", []))
        ran = report.get("tools_ran")
        ran_tools = (sorted(json.dumps([t.get("name"), t.get("digest")]) for t in ran)
                     if isinstance(ran, list) and all(isinstance(t, dict) for t in ran) else None)
        if report.get("platform") != body["next"].get("platform") or ran_tools != asked_tools:
            return {"final": {"verdict": "error", "reason": "run-report-mismatch"}, "runs": runs, "run_keys": keys}
        body = session.ask("obligation.check", {"op": "run.result", "check": check_id, "run": runs, "report": report})


def drive_check(session: Session, obligation: dict, inputs: list[dict], tools: list[dict], report_for, root: pathlib.Path = ROOT) -> dict:
    """Take one obligation through start, runs and final. `report_for(run_number, description)` returns
    the executor's report for a run, or None if there is none yet, in which case the description is returned."""
    steps = check_steps(session, obligation, inputs, tools, PLATFORM, root)
    try:
        number, description, key = next(steps)
        while True:
            report = report_for(number, description)
            if report is None:
                return {"pending": description, "run_key": key}
            number, description, key = steps.send(report)
    except StopIteration as done:
        return done.value


# What the provider said it could not make into a check, last time it was asked. A run is not
# green while this is not empty: a case that cannot be checked is not a case that passed.
REFUSED_BY_PROVIDER: list[str] = []
DECLARED_INPUTS: dict = {}  # obligation name -> the paths its checks may read, as the provider listed them


RANGE_END = r"[!-.0-9;-Z^-~]"  # printable ASCII but / : [ \\ ]
PATTERN_SEGMENT = re.compile(rf"(?:[^\[\]\\*:]|\*|\[{RANGE_END}-{RANGE_END}\])+")


def pattern_ok(pattern) -> bool:
    """A match pattern as the project file may hold it: a relative path whose segments are not empty, `.` or
    `..`, hold no backslash or colon, and use `[` only as a range `[a-b]` of two printable ASCII characters other than
    `/`, `:`, `[`, `\\` and `]`, a no later than b."""
    if not isinstance(pattern, str) or not pattern or pattern.startswith("/"):
        return False
    for seg in pattern.split("/"):
        if seg in ("", ".", "..") or not PATTERN_SEGMENT.fullmatch(seg):
            return False
        for low, high in re.findall(r"\[(.)-(.)\]", seg):
            if low > high:
                return False
    return True


def segment_matches(pattern: str, name: str) -> bool:
    """One path segment against one pattern segment: `*` is any run of characters, `[a-b]` one character from a
    to b, anything else itself. There is no `?`, no `**`, and no escape. The pattern is one pattern_ok accepts."""
    if not pattern:
        return not name
    if pattern[0] == "*":
        return any(segment_matches(pattern[1:], name[i:]) for i in range(len(name) + 1))
    if pattern[0] == "[":
        low, high = pattern[1], pattern[3]
        return bool(name) and low <= name[0] <= high and segment_matches(pattern[5:], name[1:])
    return bool(name) and name[0] == pattern[0] and segment_matches(pattern[1:], name[1:])


def is_junction(path) -> bool:
    """A Windows junction, a link that is_symlink does not report."""
    check = getattr(pathlib.Path(path), "is_junction", None)
    return bool(check and check())


class Unreadable(Exception):
    """A folder or file under the root that cannot be read: a listing without it would look whole."""


def regular_files(root: pathlib.Path) -> list[str]:
    """Every regular file under root by relative path, reached without a link (a junction included) at any step, none
    with a segment `.git`. Entries are told apart by what the folder listing says of them, not by following them; a
    folder it walks that cannot be listed raises Unreadable. A file found this way that cannot be read is found
    unreadable when it is read."""
    found, todo = [], [pathlib.Path(root)]
    while todo:
        here = todo.pop()
        try:
            entries = list(os.scandir(here))
        except OSError as err:
            raise Unreadable(f"{here}: {err}") from None
        for entry in entries:
            if entry.name == ".git" or entry.is_symlink() or is_junction(entry.path):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    todo.append(pathlib.Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    found.append(pathlib.Path(entry.path).relative_to(root).as_posix())
            except OSError as err:
                raise Unreadable(f"{entry.path}: {err}") from None
    return found


def claimed(root: pathlib.Path, patterns: list[str]) -> list[str]:
    """The regular files under root, by relative path, that one of the patterns matches segment by segment."""
    found = set()
    for rel in regular_files(root):
        parts = rel.split("/")
        if any(len(p.split("/")) == len(parts) and all(segment_matches(a, b) for a, b in zip(p.split("/"), parts)) for p in patterns):
            found.add(rel)
    return sorted(found)


def binding(name: str) -> dict:
    """A binding of the project file, by name."""
    project = tomllib.loads((ROOT / "dodona.toml").read_text(encoding="utf-8"))
    return next(b for b in project["binding"] if b["name"] == name)


def list_project(session: Session, root: pathlib.Path) -> tuple[list[dict], list[dict]]:
    files = [file_ref(root / p, root) for p in claimed(root, binding("kernel-models")["match"])]
    body = session.ask("obligation.enumerate", {"binding": "kernel-models", "definitions": [], "files": files})
    paths = [f["path"] for f in files]
    DECLARED_INPUTS.clear()
    for o in body["obligations"]:
        # What a check of it may read is the provider's word, held apart from the obligation the check is sent.
        declared = o.pop("inputs", None)
        if not isinstance(declared, list) or not all(isinstance(p, str) for p in declared) \
                or declared != sorted(set(declared)) or not set(declared) <= set(paths):
            raise Refused("bad-inputs")
        DECLARED_INPUTS[o.get("name")] = declared
    obligations = [dict(o, binding="kernel-models") for o in body["obligations"]]
    REFUSED_BY_PROVIDER[:] = sorted(r.get("name", "?") for r in body.get("rejected", []))
    names = [o["name"] for o in obligations]
    if len(names) != len(set(names)):
        raise Refused("duplicate-obligation")
    return obligations, files


def floor_digest(tool: dict) -> str:
    """The digest a result's key holds for a tool accepted from a floor version on: the floor itself, so that a newer
    build does not make results stale, and a change of floor does."""
    return hashlib.sha256(f"{tool['name']}>={tool['floor']}".encode("utf-8")).hexdigest()


def version_tuple(text) -> tuple | None:
    found = re.fullmatch(r"([0-9]+(?:\.[0-9]+)*)", text or "")
    return tuple(int(x) for x in found.group(1).split(".")) if found else None


def lock_tools() -> tuple[list[dict], dict]:
    """The tools as this site's pins give them (not yet a lock: decision 0026). A tool that is not pinned yet has a digest of zeros,
    which no measurement can equal, so nothing recorded in that state counts later. A tool pinned by a floor version has the
    floor's digest."""
    lock = json.loads((ROOT / ".github" / "site" / "pins.json").read_text(encoding="utf-8"))
    pinned = {t["name"]: t for t in lock["tools"]}
    return [{"name": n, "version": pinned[n]["version"],
             "digest": "sha256:" + (floor_digest(pinned[n]) if pinned[n].get("floor") else (pinned[n]["sha256"] or "0" * 64))}
            for n in sorted(pinned)], pinned


def tool_faults(pinned: dict, measured: dict, versions: dict) -> tuple[list, list]:
    """The tools not measured, and those measured to be other than pinned: for a floor, a version that cannot be read or is
    below the floor. Neither ever lets a run become a verdict."""
    unmeasured = [n for n in sorted(pinned) if not measured.get(pinned[n]["file"])]
    mismatched = []
    for n in sorted(pinned):
        tool = pinned[n]
        if tool.get("floor"):
            seen, floor = version_tuple(versions.get(tool["file"])), version_tuple(tool["floor"])
            # The floor or any later version, a new major release included: an upgrade of the site's tool neither
            # stops the checks nor makes their results stale (the key holds the floor); each result records the
            # version it ran on, outside the key, so a difference a new version makes stays visible.
            if seen is None or floor is None or seen < floor:
                mismatched.append(n)
        elif tool["sha256"] is not None and measured.get(tool["file"]) != tool["sha256"]:
            mismatched.append(n)
    return unmeasured, mismatched


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
    """The files the provider said a check of this obligation may read."""
    wanted = set(DECLARED_INPUTS[obligation["name"]])
    return [f for f in files if f["path"] in wanted]


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
        job = {"reachable": True, "complete": True, "exit": None, "measured": {}, "versions": {}, "fetched": None}
    else:
        job = send_job(site, bundle, cases)
    reachable, complete, measured = job["reachable"], job["complete"], job["measured"]
    if reachable and job["fetched"] is not None:
        shutil.copytree(job["fetched"], out / "outputs", dirs_exist_ok=True)
    (out / "runs.json").write_text(json.dumps({"reachable": reachable, "complete": complete, "queue_exit": job["exit"], "sent": len(cases), "plan": chosen, "pending": pending, "measured": measured, "versions": job["versions"],
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
    _, pinned = lock_tools()
    versions = sorted({where[tool["file"]] for tool in pinned.values() if tool.get("floor") and tool["file"] in where})
    (bundle / "manifest.json").write_text(json.dumps({"out": "out", "cases": cases, "measure": sorted(set(where.values())), "versions": versions},
                                                     indent=1), encoding="utf-8")
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
    seen_versions = json.loads((fetched / "versions.json").read_text(encoding="utf-8")) if (fetched / "versions.json").exists() else {}
    marker = fetched / "complete.json"
    marked = marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("cases") == [c["name"] for c in cases]
    complete = bool(reachable and code == 0 and marked)
    if reachable and not complete:
        print(f"the job did not end well (the executor's client exited with {code}; end marker {'present' if marked else 'missing'}); "
              "nothing from it will be taken as a result")
    return {"reachable": bool(reachable), "complete": complete, "exit": code, "fetched": fetched,
            "measured": {name: seen.get(path) for name, path in where.items()},
            "versions": {name: seen_versions.get(path) for name, path in where.items() if path in seen_versions}}


def job_tool_faults(runs: dict) -> tuple[list, list]:
    """The tools of a job not measured, and those measured to be other than pinned, from what the job recorded."""
    _, pinned = lock_tools()
    versions = runs.get("versions", {})
    return tool_faults(pinned, runs.get("measured", {}), versions if isinstance(versions, dict) else {})


def job_fault(runs: dict) -> str | None:
    """Why nothing from this job may be judged, measured against this site's pins; None if it may."""
    unmeasured, mismatched = job_tool_faults(runs)
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
    unmeasured, mismatched = job_tool_faults(runs)
    # The key is made from what was measured to have run; for a floor tool, from its floor, once its version is checked.
    ran = [{"name": n, "digest": "sha256:" + (floor_digest(pinned[n]) if pinned[n].get("floor") else (measured.get(pinned[n]["file"]) or "0" * 64))}
           for n in sorted(pinned)]
    unpinned = [n for n in sorted(pinned) if pinned[n]["sha256"] is None and not pinned[n].get("floor")]
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
                        "executor": runs["executor"], "unpinned_tools": unpinned,
                        # What the job found, outside the key: a tool pinned by a floor keeps its results across builds.
                        "tools_measured": {n: {"digest": measured.get(pinned[n]["file"]), "version": runs.get("versions", {}).get(pinned[n]["file"])}
                                           for n in sorted(pinned)}}
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
    try:
        asked = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except ValueError:
        asked = None
    if not isinstance(asked, dict):
        print(json.dumps({"outcome": "refused", "reason": "bad-input"}))
        return 0

    def report_for(number, description):
        given = {"number": number, "run_key": run_key(check_key, number, description), "run": description}
        wall = description.get("limits", {}).get("wall_ms")
        # At least wall_ms plus 60 seconds, and 24 hours at most; with no wall_ms, the 24 hours.
        wait = min(wall / 1000 + 60, 86_400) if isinstance(wall, int) else 86_400
        # The executor runs in a process group (Unix) or job (Windows) of its own, and everything in it is
        # ended when it returns, so a run cannot leave work behind it.
        try:
            tree = Session._start(asked["executor"], root)  # started in the project's root
        except OSError:
            return {"end": "executor-failed"}
        try:
            out, _ = tree.proc.communicate(json.dumps(given).encode("utf-8"), timeout=wait)
            # The report is read as a message is: its first line, ended by a line feed alone.
            line = out.split(b"\n", 1)[0]
            if b"\n" not in out or line.endswith(b"\r") or line.startswith(b"\xef\xbb\xbf"):
                raise Refused("framing")
            report = strict_load(line)
        except subprocess.TimeoutExpired:
            return {"end": "timed-out"}
        except (OSError, Refused):
            return {"end": "executor-failed"}
        finally:
            tree.end()
        return report if tree.proc.returncode == 0 and isinstance(report, dict) else {"end": "executor-failed"}

    def strings(value):
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    shaped = (isinstance(asked.get("root"), str) and strings(asked.get("provider")) and asked["provider"] and strings(asked.get("executor"))
              and asked["executor"] and isinstance(asked.get("obligation"), dict) and strings(asked["obligation"].get("specified_by"))
              and strings(asked["obligation"].get("targets")) and isinstance(asked.get("inputs"), list)
              and all(isinstance(i, dict) and isinstance(i.get("path"), str) and isinstance(i.get("identity"), str) for i in asked["inputs"])
              and isinstance(asked.get("tools"), list)
              and all(isinstance(t, dict) and isinstance(t.get("name"), str) and isinstance(t.get("digest"), str) for t in asked["tools"])
              and isinstance(asked.get("platform"), dict) and type(asked.get("deadline_ms")) is int and asked["deadline_ms"] > 0)
    if not shaped:
        print(json.dumps({"outcome": "refused", "reason": "bad-input"}))  # before the provider is started
        return 0
    root = pathlib.Path(asked["root"]).resolve()
    PLATFORM = asked["platform"]
    check_key = canonical.identity({"obligation": asked["obligation"], "inputs": asked["inputs"]})
    named = set(asked["obligation"].get("specified_by", []) + asked["obligation"].get("targets", []))
    if not named <= {f["path"] for f in asked["inputs"]}:
        print(json.dumps({"outcome": "refused", "reason": "unknown-file"}))  # before the provider is started
        return 0
    session = None
    try:
        session = Session(asked["provider"], root, [], deadline_ms=asked.get("deadline_ms", 60000))
        driven = drive_check(session, asked["obligation"], asked["inputs"], asked["tools"], report_for, root)
        verdict = "unavailable" if driven.get("unavailable") else driven["final"]["verdict"]
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
