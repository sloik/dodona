"""Judge a command that reports a project's status (decision 0034).

    python tools/run_status_cases.py --kernel KERNEL... [--jobs N] [--variants] -- STATUS COMMAND...

Each case in conformance/project/cases.json is a small project, set up afresh in a directory of
its own, with providers that answer from a file of the case (conformance/project/fixture_provider.py)
and ledgers written by the reference encoder. The command under judgement and the reference,
tools/project_status.py, are each run on their own copy. A case matches when:

- a refusal is expected and the command refuses with that reason;
- otherwise the command does not refuse; what it judged, the coverage, the ledger note, the bindings
  it does not serve, the obligations nobody can check and the policy source equal the reference's;
  every request it sent its providers equals the reference's; its report is exactly what KERNEL's
  `scenario` command gives as the last result for what it judged; and the statuses the case names,
  written by hand from the status rules, are the report's.

The curated refusals and statuses are never taken from a kernel. KERNEL recomputes the report
from the reference's scenario, which must equal what the command says it judged.
An incomplete process or broken reference premise leaves the case unfinished.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import errno
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402
import host  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = ROOT / "conformance" / "project" / "cases.json"
FIXTURE = ROOT / "conformance" / "project" / "fixture_provider.py"
REFERENCE = [sys.executable, str(ROOT / "tools" / "project_status.py")]


class Skip(Exception):
    """A case this system cannot set up, such as one that needs a symbolic link. Never a match."""


class Unfinished(Exception):
    """The judge lacks a completed answer or a usable reference premise."""


def same(a, b) -> bool:
    """Equal as JSON text, so that 0 and false, or 1 and 1.0, are not taken for each other."""
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


REFERENCE_FIELDS = {"judged": dict, "coverage": dict, "ledger": dict, "not_served": list, "not_checkable": list,
                    "policy_not_applied": list, "policy_source": str, "project_doubts": list}
COMPARED = tuple(REFERENCE_FIELDS)
OUT_KEYS = set(COMPARED) | {"report", "project_status"}


def ledger_bytes(entries: list[dict]) -> bytes:
    out, previous = b"", None
    for e in entries:
        entry = {"previous": previous, "kind": e["kind"], "body": e["body"]}
        raw = canonical.encode(entry).encode("utf-8")
        out += b"dodona1 %d %s " % (len(raw), hashlib.sha256(raw).hexdigest().encode("ascii")) + raw + b"\n"
        previous = canonical.identity(entry)
    return out


def fill(value, preimages: dict):
    """Placeholders in a case's ledger entries: `$preimage:NAME` and `$key:NAME` stand for the obligation's
    preimage as things stand, and its identity; `$baseline:ID` for the intent's baseline as the status rules
    define it. All come from the reference's view of the project, never from a kernel."""
    if isinstance(value, str) and value.startswith("$preimage:"):
        return preimages.get(value[len("$preimage:"):], {})
    if isinstance(value, str) and value.startswith("$key:"):
        return canonical.identity(preimages.get(value[len("$key:"):], {}))
    if isinstance(value, str) and value.startswith("$baseline:"):
        it = preimages.get("$intents", {}).get(value[len("$baseline:"):], {})
        return canonical.identity({"owner": it.get("owner"), "words": it.get("words", ""), "children": canonical.sort_set(it.get("children", [])),
                                   "criteria": {c: {"words": v.get("words", ""), "gate": v["gate"], "checked_by": canonical.sort_set(v["checked_by"])}
                                                for c, v in it.get("criteria", {}).items()}})
    if isinstance(value, dict):
        return {k: fill(v, preimages) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, preimages) for v in value]
    return value


def make_link(target: pathlib.Path, link: pathlib.Path, *, symbolic: bool = True) -> None:
    kind = "a symbolic" if symbolic else "a hard"
    try:
        (os.symlink if symbolic else os.link)(target, link)
    except NotImplementedError:
        raise Skip(f"this system cannot make {kind} link") from None
    except OSError as err:
        unsupported = (errno.ENOSYS, getattr(errno, "ENOTSUP", -1), getattr(errno, "EOPNOTSUPP", -1))
        if isinstance(err, PermissionError) or err.errno in unsupported or getattr(err, "winerror", None) in (1, 50, 1314):
            raise Skip(f"this system cannot make {kind} link") from err
        raise


def set_up(case: dict, site: dict, where: pathlib.Path, preimages: dict) -> tuple[bytes, pathlib.Path, pathlib.Path]:
    """The project of a case in where/root, the providers' answer files and records in where/aux; returns the input."""
    root, aux = where / "root", where / "aux"
    root.mkdir(parents=True)
    aux.mkdir()
    for rel, text in case["files"].items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text.encode("utf-8"))
    for rel, target in case.get("links", {}).items():
        make_link(root / target, root / rel)
    providers = {}
    for name, p in case["providers"].items():
        answers, record = aux / f"{name}.answers.json", aux / f"{name}.record.jsonl"
        answers.write_text(json.dumps(p["answers"], ensure_ascii=False), encoding="utf-8")
        providers[name] = {"command": [sys.executable, str(FIXTURE), str(answers), str(record)], "code": p["code"]}
    owner = case.get("owner_ledger")
    if owner is not None:
        (root / "records").mkdir(exist_ok=True)
        if "raw" in owner:
            data = owner["raw"].encode("utf-8")
        else:
            data = ledger_bytes(fill(owner["entries"], preimages)) + owner.get("torn_tail", "").encode("utf-8")
            if "edit" in owner:  # an entry changed after it was written: its checksum no longer matches
                data = data.replace(owner["edit"][0].encode("utf-8"), owner["edit"][1].encode("utf-8"), 1)
            if owner.get("strip_last_newline"):
                data = data[:-1]
        if owner.get("folder_link"):
            (root / "records").rmdir()
            (root / "records-real").mkdir()
            (root / "records-real" / "owner.ledger").write_bytes(data)
            make_link(root / "records-real", root / "records")
        elif owner.get("link"):
            (root / "records" / "elsewhere.ledger").write_bytes(data)
            make_link(root / "records" / "elsewhere.ledger", root / "records" / "owner.ledger")
        else:
            (root / "records" / "owner.ledger").write_bytes(data)
    ledgers = []
    for item in case["ledgers"]:
        ledgers.append(item["path"])
        if item.get("absent"):
            continue
        if any(item["path"].startswith(rel + "/") for rel in case.get("outside_links", {})):
            continue  # written in the outside folder the link leads to
        path = root / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if item.get("dangling"):
            make_link(root / "l" / "nothing-here.ledger", path)
            continue
        if item.get("hardlink_to_owner"):
            make_link(root / "records" / "owner.ledger", path, symbolic=False)
            continue
        if item.get("link_to"):
            (root / item["link_to"]).write_bytes(ledger_bytes(fill(item["entries"], preimages)))
            make_link(root / item["link_to"], path)
            continue
        if item.get("link_to_owner"):
            make_link(root / "records" / "owner.ledger", path)
            continue
        if "raw_entries" in item:  # entries the reference encoder writes whole, chained, whatever they hold
            data = ledger_bytes(item["raw_entries"])
        else:
            data = item["raw"].encode("utf-8") if "raw" in item else ledger_bytes(fill(item["entries"], preimages))
        path.write_bytes(data + item.get("torn_tail", "").encode("utf-8"))
    if "raw_input" in case:
        return case["raw_input"].encode("utf-8"), root, aux
    asked = {"root": str(root), "project": "dodona.toml", "site": copy.deepcopy(dict(site, providers=providers, **case.get("site_edit", {}))),
             "policy": copy.deepcopy(case["policy"]),
             "policy_source": "policy: as the judge gives it", "ledgers": ledgers, "owner_ledger": "records/owner.ledger"}
    for path, value in case.get("input_edit", []):
        here = asked
        for key in path[:-1]:
            here = here[key]
        if value == "$delete":
            del here[path[-1]]
        else:
            here[path[-1]] = value
    for rel, spec in case.get("outside_links", {}).items():
        # A link from inside the root to a folder outside it (in aux), which may be locked or missing.
        target = aux / ("outside-" + rel.replace("/", "-"))
        if not spec.get("missing"):
            target.mkdir()
            for item in case["ledgers"]:
                if item["path"].startswith(rel + "/") and "entries" in item:
                    (target / item["path"][len(rel) + 1:]).write_bytes(ledger_bytes(fill(item["entries"], preimages)))
        make_link(target, root / rel)
        if "mode" in spec:
            if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
                raise Skip("this system cannot make a folder its own user cannot enter")
            os.chmod(target, spec["mode"])
    for rel, mode in case.get("unreadable_mode", {}).items():
        if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
            raise Skip("this system cannot make a file or folder its own user cannot read")
        os.chmod(root / rel, mode)
    for rel in case.get("unreadable", []):
        if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
            raise Skip("this system cannot make a folder or file its own user cannot read")
        os.chmod(root / rel, 0)
    return json.dumps(asked, ensure_ascii=False).encode("utf-8") + case.get("stdin_suffix", "").encode("utf-8"), root, aux


def requests(aux: pathlib.Path) -> dict:
    """What each provider was asked, without the parts a host chooses for itself (ids, echo, limits). A provider
    started at all has a record, empty if it was sent nothing."""
    seen = {}
    for record in sorted(aux.glob("*.record.jsonl")):
        lines = [json.loads(l) for l in record.read_text(encoding="utf-8").splitlines() if l.strip()]
        # hello as sent, but for its echo, which a host chooses: its protocol and limits are compared.
        # A run.result names its check by the id of the start request, which a host chooses: left out.
        seen[record.name] = [{"type": m.get("type"), "capability": m.get("capability"),
                              "body": ({k: v for k, v in m["body"].items() if k != "check"} if isinstance(m.get("body"), dict) else m.get("body")),
                              "protocol": m.get("protocol"), "limits": m.get("limits"), "deadline_ms": m.get("deadline_ms")} for m in lines]
    return seen


def answer(command: list[str], stdin: bytes, role: str, *, cwd: pathlib.Path | None = None,
           env: dict | None = None, timeout: int = 120) -> dict:
    try:
        done = subprocess.run(command, input=stdin, capture_output=True, timeout=timeout, cwd=cwd, env=env)
    except OSError as err:
        raise Unfinished(f"{role} could not start: {err}") from err
    except subprocess.TimeoutExpired as err:
        raise Unfinished(f"{role} timed out") from err
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace")[-300:]
        raise Unfinished(f"{role} exited with {done.returncode}: {detail}")
    try:
        # A report carries ledger entries up to 64 levels deep, so it can nest deeper.
        result = host.strict_load(done.stdout.rstrip(b"\n"), limit=None)
    except (host.Refused, RecursionError) as err:
        raise Unfinished(f"{role} gave invalid JSON: {err}") from err
    if not isinstance(result, dict):
        raise Unfinished(f"{role} gave no JSON object")
    return result


def run(command: list[str], case: dict, site: dict, preimages: dict, role: str) -> tuple[dict, dict]:
    with tempfile.TemporaryDirectory() as tmp:
        where = pathlib.Path(tmp)
        root, aux = where / "root", where / "aux"
        try:
            stdin, root, aux = set_up(case, site, where, preimages)
            cwd = None
            if case.get("started_in_root"):  # so that a root read as "wherever the command was started" finds the project
                command = [str(pathlib.Path(arg).resolve()) if pathlib.Path(arg).is_file() else arg for arg in command]
                cwd = root
            env = dict(os.environ, PWD=str(root)) if cwd else None  # so a command that reads $PWD finds the project too
            got = answer(command, stdin, role, cwd=cwd, env=env)
            return got, requests(aux)
        finally:
            closed = [root / rel for rel in list(case.get("unreadable", [])) + list(case.get("unreadable_mode", {}))]
            closed.extend(aux / ("outside-" + rel.replace("/", "-")) for rel, spec in case.get("outside_links", {}).items()
                          if "mode" in spec and not spec.get("missing"))
            for path in closed:
                try:
                    os.chmod(path, 0o755)  # so the fixture can be removed, including after partial setup
                except FileNotFoundError:
                    pass


def refusal(answer: dict) -> bool:
    return set(answer) == {"refused", "detail"} and isinstance(answer["refused"], str) and isinstance(answer["detail"], str)


def reference_status(case: dict, site: dict, preimages: dict) -> tuple[dict, dict]:
    ref, asked = run(REFERENCE, case, site, preimages, "reference status")
    if "refused" in ref:
        if not refusal(ref):
            raise Unfinished("the reference gave a malformed refusal")
        return ref, asked
    if set(ref) != set(COMPARED) or any(not isinstance(ref[key], kind) for key, kind in REFERENCE_FIELDS.items()):
        raise Unfinished("the reference gave no complete status premise")
    view = ref["judged"]
    if not (view.get("kind") == "status" and view.get("name") == "this-project"
            and all(isinstance(view.get(key), dict) for key in ("self", "policy", "obligations", "intents"))
            and isinstance(view.get("steps"), list) and view["steps"] and all(isinstance(step, dict) for step in view["steps"])):
        raise Unfinished("the reference gave no scenario to judge")
    return ref, asked


def _preimages(case: dict, site: dict) -> dict:
    bare = dict(case, ledgers=[], owner_ledger=None, input_edit=[], unreadable=[], unreadable_mode={})
    ref, _ = reference_status(bare, site, {})
    if "refused" in ref:
        return {}  # a fixture can be refused before it gets to any of its ledger contents
    view = ref["judged"]
    found = {n: o["preimage"] for n, o in view["obligations"].items()}
    found["$intents"] = view["intents"]
    return found


def scenario_report(kernel: list[str], view: dict, *, timeout: int = 120) -> dict:
    got = answer(kernel + ["scenario"], json.dumps(view).encode("utf-8"), "independent scenario", timeout=timeout)
    results = got.get("results")
    if (set(got) != {"results"} or not isinstance(results, list) or len(results) != len(view["steps"])
            or any(not isinstance(item, dict) for item in results)):
        raise Unfinished("the independent scenario gave no complete set of results")
    report = results[-1]
    if not (set(report) == {"obligations", "intents", "project", "rejected"}
            and isinstance(report["project"], dict) and isinstance(report["project"].get("status"), str)
            and type(report["rejected"]) is int):
        raise Unfinished("the independent scenario gave no final status report")
    for field in ("obligations", "intents"):
        group = report[field]
        if not (isinstance(group, dict) and all(isinstance(item, dict) and isinstance(item.get("status"), str)
                                               for item in group.values())):
            raise Unfinished(f"the independent scenario gave no usable {field} report")
    return report


def expected_differences(out: dict, report: dict, headline: str, expect: dict) -> list[str]:
    problems = []
    status = expect.get("status", {})
    for group in ("obligations", "intents"):
        for name, want in status.get(group, {}).items():
            if report[group].get(name, {}).get("status") != want:
                problems.append(f"{group} {name}: expected {want}")
    if "project" in status and report["project"]["status"] != status["project"]:
        problems.append(f"project: expected {status['project']}, got {report['project']}")
    if "project_status" in expect and headline != expect["project_status"]:
        problems.append(f"project_status: expected {expect['project_status']}, got {headline}")
    for field in ("not_served", "not_checkable", "ledger", "policy_not_applied", "project_doubts"):
        if field in expect and not same(out[field], expect[field]):
            problems.append(f"{field}: expected {expect[field]}, got {out[field]}")
    return problems


def judge(case: dict, site: dict, command: list[str], kernel: list[str], generated: bool = False) -> list[str]:
    # The current preimages, for ledgers that hold results under the current key: from the reference.
    needs_preimages = "$" in json.dumps(case["ledgers"]) + json.dumps(case.get("owner_ledger"))
    preimages = _preimages(case, site) if needs_preimages else {}
    got, asked = run(command, case, site, preimages, "status command")
    ref, ref_asked = reference_status(case, site, preimages)
    expect = ({"refused": ref["refused"]} if "refused" in ref else {}) if generated else case["expect"]
    if "refused" in expect:
        if ref.get("refused") != expect["refused"]:
            raise Unfinished(f"the reference did not give the fixture's refusal {expect['refused']}")
    elif "refused" in ref:
        raise Unfinished(f"the reference refused {ref['refused']} where the fixture expects a report")
    elif needs_preimages and not preimages:
        raise Unfinished("the reference refused to read the fixture's preimages")

    problems = []
    deadline = dict(site, **case.get("site_edit", {})).get("deadline_ms")
    for path, value in case.get("input_edit", []):
        if path == ["site", "deadline_ms"]:
            deadline = value
    if type(deadline) is int:
        # Judged against the input, not the reference: hello and every request carry the deadline exactly as given.
        sent = [m for record in asked.values() for m in record if m["type"] in ("hello", "request")]
        late = [m for m in sent if (m["limits"] or {}).get("deadline_ms", m["deadline_ms"]) != deadline]
        if late:
            problems.append(f"a provider was sent a deadline other than the {deadline} ms given")
    if "refused" in expect:
        if not refusal(got) or got["refused"] != expect["refused"]:
            problems.append(f"expected exactly refused {expect['refused']} with a detail, got {json.dumps(got)[:200]}")
        # Nothing after the broken rule is done: the providers started, and what each was asked, are the reference's.
        if not same(asked, ref_asked):
            problems.append(f"refused at {expect['refused']}, but the providers started or asked differ from the reference's")
        return problems

    # Use the known input even if the command's `judged` is itself wrong.
    own = scenario_report(kernel, ref["judged"])
    status = own["project"]["status"]
    headline = "unknown" if ref["project_doubts"] and status in ("passed", "nothing-required") else status
    wrong_premises = expected_differences(ref, own, headline, expect)
    if wrong_premises:
        raise Unfinished("the reference and independent scenario disagree with the fixture: " + "; ".join(wrong_premises))
    if "refused" in got:
        return problems + [f"refused {got['refused']} ({got.get('detail')}), expected a report"]
    if set(got) != OUT_KEYS:
        problems.append(f"the answer holds {sorted(set(got) ^ OUT_KEYS)} where it should not or does not")
    for field in COMPARED:
        if not same(got.get(field), ref[field]):
            problems.append(f"{field} differs from the reference")
    if not same(asked, ref_asked):
        problems.append("the requests sent to the providers differ from the reference's")
    if not same(got.get("report"), own):
        problems.append("the report is not what the scenario command gives for what was judged")
    if got.get("project_status") != headline:
        problems.append("project_status is not the report's status as its doubts allow")
    return problems


def wrong_values(value) -> list:
    """Values of another kind than `value`: null, and one of each other JSON type."""
    out = [None]
    for other in (True, 7, "x", [], {}):
        if type(other) is not type(value) and not (isinstance(value, bool) and isinstance(other, bool)):
            out.append(other)
    return out


def leaf_paths(value, path=()):
    """Every path into a JSON value, objects and lists included."""
    yield path
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaf_paths(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from leaf_paths(v, path + (i,))


def changed(value, path, new, delete=False):
    value = copy.deepcopy(value)
    here = value
    for key in path[:-1]:
        here = here[key]
    if delete:
        del here[path[-1]]
    else:
        here[path[-1]] = new
    return value


def variants(spec: dict) -> list[dict]:
    """Cases made from the reported cases by taking each field of each provider's answer, and of the policy, away or
    giving it a value of another kind. The answer each must get is the reference's, never a kernel's."""
    out = []
    bases = [c for c in spec["cases"] if c["name"] in VARIANT_BASES]
    for base in bases:
        for provider, entry in base["providers"].items():
            answers = entry["answers"]
            for path in leaf_paths(answers):
                if not path or path[0] == "wrong_echo":
                    continue
                here = answers
                for key in path:
                    here = here[key]
                options = [("deleted", None, True)] + [(f"set to {json.dumps(v)}", v, False) for v in wrong_values(here)]
                for label, new, delete in options:
                    case = copy.deepcopy(base)
                    case["providers"][provider]["answers"] = changed(answers, path, new, delete)
                    case["name"] = f"{base['name']} / {provider} {'.'.join(map(str, path))} {label}"
                    out.append(case)
        for path in leaf_paths(base["policy"]):
            if not path:
                continue
            here = base["policy"]
            for key in path:
                here = here[key]
            for label, new, delete in [("deleted", None, True)] + [(f"set to {json.dumps(v)}", v, False) for v in wrong_values(here)]:
                case = copy.deepcopy(base)
                case["policy"] = changed(base["policy"], path, new, delete)
                case["name"] = f"{base['name']} / policy {'.'.join(map(str, path))} {label}"
                out.append(case)
        # The input's own fields, taken away or of another kind.
        with tempfile.TemporaryDirectory() as tmp:
            sample = json.loads(set_up(base, spec["site"], pathlib.Path(tmp), {})[0])
        sample.pop("policy")  # its fields are varied above
        for path in leaf_paths(sample):
            if not path or path == ("root",):
                continue
            here = sample
            for key in path:
                here = here[key]
            for label, new in [("deleted", "$delete")] + [(f"set to {json.dumps(v)}", v) for v in wrong_values(here)]:
                case = copy.deepcopy(base)
                case["input_edit"] = case.get("input_edit", []) + [[list(path), new]]
                case["name"] = f"{base['name']} / input {'.'.join(map(str, path))} {label}"
                out.append(case)
        # The project file, one line at a time, written each way the subset might be read differently.
        lines = base["files"]["dodona.toml"].split("\n")
        edits = [("a tab for a space", lambda l: l.replace(" ", "\t", 1)), ("spaces around the line", lambda l: " " + l + " "),
                 ("no spaces around =", lambda l: l.replace(" = ", "=", 1)), ("two spaces after =", lambda l: l.replace(" = ", " =  ", 1)),
                 ("a carriage return at the end", lambda l: l + "\r"), ("DEL inside", lambda l: l.replace('"', '"\x7f', 1)),
                 ("a comment without a space", lambda l: l + "# note"), ("a comment after a space", lambda l: l + " # note"),
                 ("a trailing comma in a list", lambda l: l.replace('"]', '",]', 1)), ("no space after a comma", lambda l: l.replace('", "', '","')),
                 ("spaces inside the brackets", lambda l: l.replace('["', '[ "', 1).replace('"]', '" ]', 1)),
                 ("a digit in the key", lambda l: l.replace(" = ", "2 = ", 1)), ("the line twice", lambda l: l + "\n" + l)]
        for i, line in enumerate(lines):
            for label, edit in edits:
                new = edit(line)
                if new == line:
                    continue
                case = copy.deepcopy(base)
                case["files"]["dodona.toml"] = "\n".join(lines[:i] + [new] + lines[i + 1:])
                case["name"] = f"{base['name']} / project line {i + 1} {label}"
                out.append(case)
    return out


VARIANT_BASES = ("an empty ledger has a report", "a project with two bindings, a tree and tools", "a confirmed intent with its check passed is fulfilled",
                 "policy no status rule applies keeps the project from passing", "two ledgers are read in order", "an intent tree")


def main() -> int:
    # Case names hold characters a Windows console cannot show; they are printed escaped rather than crash the judge.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kernel", nargs="+", required=True, help="a kernel command whose `scenario` recomputes the report")
    ap.add_argument("--variants", action="store_true",
                    help="also judge every field of the reported cases' answers and policy taken away or of another kind, "
                         "against the reference's answer (slower)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2, help="cases judged at once, each in a folder of its own")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    kernel = args.kernel
    if "--" in kernel:
        kernel, command = kernel[:kernel.index("--")], kernel[kernel.index("--") + 1:]
    def one(case: dict) -> list[str] | Exception:
        try:
            return judge(case, spec["site"], command, kernel, generated=args.variants)
        except Exception as err:  # fixture and process failures need a result too
            return err

    try:
        spec = json.loads(CASES.read_text(encoding="utf-8"))
        cases = variants(spec) if args.variants else spec["cases"]
        names = [case["name"] for case in cases]
        if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
            raise ValueError("cases must have distinct nonempty names")
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(one, cases))
    except Exception as err:
        print(f"UNFINISHED the judge could not prepare its cases: {type(err).__name__}: {err}")
        return finish(0, 0, 0, [], 1)

    matched = skipped = unfinished = 0
    rejected = []
    for name, result in zip(names, results, strict=True):
        if isinstance(result, Skip):
            skipped += 1
            print(f"skipped  {name}: {result}")
        elif isinstance(result, Exception):
            unfinished += 1
            print(f"UNFINISHED {name}: {type(result).__name__}: {result}")
        elif result:
            rejected.append(name)
            print(f"MISMATCH {name}: " + "; ".join(result))
        else:
            matched += 1
            print(f"match    {name}")
    return finish(len(cases), skipped, matched, rejected, unfinished)


def finish(cases: int, skipped: int, matched: int, rejected: list[str], unfinished: int) -> int:
    judged = cases - skipped
    all_matched = judged > 0 and unfinished == 0 and not rejected
    print(json.dumps({"cases": cases, "judged": judged, "skipped": skipped, "matched": matched, "all_matched": all_matched,
                      "rejected": rejected, "unfinished": unfinished}))
    if unfinished or not judged:
        return 2
    return 0 if all_matched else 1


if __name__ == "__main__":
    sys.exit(main())
