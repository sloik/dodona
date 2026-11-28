"""Validate the schemas, guide examples, policy, project criteria and draft lock fixtures.

    python tools/check_examples.py
    python tools/check_examples.py --evidence-ledger PATH

Stage-0 helper (decision 0023). Unlike the other helpers this one needs a
third-party package, `jsonschema`, because a JSON Schema validator is not in
the standard library. It runs in CI with a pinned version. Without the package
it says so and fails: a check that silently does nothing is not a check.
Status controls exercise the policy identity requirement and absence of evidence or acts.

Exit status is 0 only if the schemas, examples, policy and project criteria validate.
The evidence-strength, status-policy, project criteria and draft lock controls
must also give the expected results.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import pathlib
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
INTENT_CRITERIA_SCHEMA = "project-intent-criteria.schema.json"


def protocol_schemas() -> tuple[dict, object]:
    """Read the repository's schema references into a local registry."""
    from referencing import Registry, Resource

    schemas = {path.name: json.loads(path.read_text(encoding="utf-8"))
               for path in sorted((ROOT / "protocol").glob("*.schema.json"))}
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema))
                                         for schema in schemas.values())
    return schemas, registry


def protocol_validator(filename: str):
    from jsonschema import Draft202012Validator

    schemas, registry = protocol_schemas()
    schema = schemas[filename]
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry)


def check_intent_criteria(validator) -> tuple[int, list[str]]:
    """Check the decoded criteria value separately from the Markdown reader's criteria rules."""
    import intents

    problems = []
    paths = sorted((ROOT / "intents").glob("[0-9]*.md"))
    if not paths:
        problems.append("no project intent files found")
    for path in paths:
        name = path.relative_to(ROOT)
        try:
            front, _ = intents.front(path.read_text(encoding="utf-8"))
            criteria = json.loads(front["criteria"])
        except (intents.Unreadable, KeyError, json.JSONDecodeError, OSError) as err:
            problems.append(f"{name}: could not decode criteria: {err}")
            continue
        for err in validator.iter_errors(criteria):
            problems.append(f"{name}: criteria{err.json_path[1:]}: {err.message}")

    deferred = {"id": "1", "words": "Replay the sample", "gate": "deferred", "condition": "the sample is replayed"}
    valid_deferred = dict(deferred, limit_days=90)
    if not validator.is_valid([valid_deferred]):
        problems.append("project intent criteria schema refuses a deferred criterion with a valid observation and limit")
    if validator.is_valid([deferred]):
        problems.append("project intent criteria schema accepts a deferred criterion without limit_days")
    if validator.is_valid([dict(valid_deferred, id="abc")]):
        problems.append("project intent criteria schema accepts a criterion ID with letters")
    return len(paths), problems


def lock_platform_problems(lock: dict) -> list[str]:
    """Report repeated exact platforms within each structurally valid lock entry."""
    problems = []
    for entry in lock["entries"]:
        seen = set()
        for pin in entry["platforms"]:
            platform = json.dumps(pin["platform"], sort_keys=True)
            if platform in seen:
                problems.append(f"{entry['kind']} {entry['name']}: repeated platform {platform}")
            seen.add(platform)
    return problems


def check_lock_platform_fixtures(validator=None) -> list[str]:
    """Judge the same offline fixtures with or without the optional schema validator."""
    vectors = json.loads((ROOT / "conformance/vectors/tool-tree.json").read_text(encoding="utf-8"))
    digests = {case["name"]: case["digest"] for case in vectors["accept"]}
    linux = {"os": "linux", "arch": "x86_64"}
    linux_gnu = dict(linux, libc="gnu")
    windows = {"os": "windows", "arch": "x86_64"}
    duplicate = 'tool sample-tool: repeated platform {"arch": "x86_64", "libc": "gnu", "os": "linux"}'
    fixtures = [
        ("different operating systems", linux_gnu, windows, []),
        ("different libc values", linux_gnu, dict(linux, libc="musl"), []),
        ("omitted libc", linux, linux_gnu, []),
        ("omitted emulation", windows, dict(windows, emulated_on="aarch64"), []),
        ("conflicting digests on one exact platform", linux_gnu, {"libc": "gnu", **linux}, [duplicate]),
    ]
    problems = []
    for label, first, second, expected in fixtures:
        lock = {
            "lock": "0.2",
            "entries": [{
                "kind": "tool",
                "name": "sample-tool",
                "version": "1.0.0",
                "requires": [],
                "platforms": [
                    {"platform": first, "digest": digests["two files"],
                     "upstream": {"source": "fixture:sample-tool-a", "published_digest": "sha256:" + "a" * 64}},
                    {"platform": second, "digest": digests["with a link inside the tree"],
                     "upstream": {"source": "fixture:sample-tool-b", "published_digest": "sha256:" + "b" * 64}},
                ],
            }],
        }
        if validator is not None:
            error = next(validator.iter_errors(lock), None)
            if error is not None:
                problems.append(f"lock fixture {label}: draft schema rejects the shape: {error.message}")
                continue
        actual = lock_platform_problems(lock)
        if actual != expected:
            problems.append(f"lock fixture {label}: expected {expected}, got {actual}")
    return problems


def evidence_strength_problems(validator) -> list[str]:
    """Validate paired synthetic records that differ only by the presence of strength."""
    digest = "sha256:" + "0" * 64
    record = {
        "record": digest, "obligation": digest, "core_key": digest,
        "platform": {"os": "linux", "arch": "x86_64"}, "verdict": "passed",
        "inputs": {"specified_by": [digest], "targets": [digest], "closure": [],
                   "tools": [], "config": digest, "expect": "holds"},
        "provider": {"name": "fixture", "version": "1", "protocol": "0.2"},
        "executor": {"name": "fixture", "version": "1"}, "isolation": "none",
        "origin": {"writer": "fixture"}, "runs": [{"exit_status": 0, "output": digest, "tools_ran": []}],
    }
    problems = []
    for kind, needs_strength in (("check", True), ("conformance", True), ("build", False)):
        without_strength = dict(record, kind=kind)
        with_strength = dict(without_strength, strength={"class": "test", "rank": "sampled"})
        invalid, valid = ((without_strength, with_strength) if needs_strength else (with_strength, without_strength))
        errors = list(validator.iter_errors(valid))
        if errors:
            problems.append(f"evidence {kind} control: {errors[0].message}")
        if validator.is_valid(invalid):
            wrong = "without strength" if needs_strength else "with strength"
            problems.append(f"evidence {kind}: accepts a record {wrong}")
    return problems


def check_evidence_ledger(path: pathlib.Path, validators: dict) -> int:
    """Judge every complete evidence body in the ledger that will be kept."""
    import ledger

    counts = {"native": 0, "stage0": 0}
    problems = []
    try:
        data = ledger.read(path)
    except (ledger.Corrupt, OSError) as err:
        print(f"PROBLEM {path}: {err}")
        return 1
    if data["torn"]:
        problems.append("the ledger ends in an incomplete entry")
    bodies = 0
    for index, entry in enumerate(data["entries"], 1):
        if entry["kind"] != "evidence":
            continue
        bodies += 1
        body = entry["body"]
        errors = {kind: next(validator.iter_errors(body), None) for kind, validator in validators.items()}
        accepted = [kind for kind, error in errors.items() if error is None]
        if len(accepted) == 1:
            counts[accepted[0]] += 1
        elif accepted:
            problems.append(f"#{index} evidence matches more than one schema")
        else:
            reasons = [f"{kind} {error.json_path}: {error.message[:160]}" for kind, error in errors.items()]
            problems.append(f"#{index} evidence is invalid ({', '.join(reasons)})")
    if not bodies:
        problems.append("the ledger contains no evidence")
    for message in problems:
        print(f"PROBLEM {path}: {message}")
    print(json.dumps({"evidence": counts, "problems": len(problems)}))
    return 1 if problems else 0


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument("--evidence-ledger", type=pathlib.Path, metavar="PATH",
                     help="validate the evidence bodies in a complete native or retained ledger")
    args = cli.parse_args()
    try:
        import jsonschema
    except ImportError:
        print("the jsonschema package is not installed; nothing was checked")
        return 1
    problems = []
    schemas, registry = protocol_schemas()
    if args.evidence_ledger is not None:
        validators = {}
        for kind, name in (("native", "project-evidence.schema.json"), ("stage0", "stage0-evidence.schema.json")):
            schema = schemas[name]
            jsonschema.Draft202012Validator.check_schema(schema)
            validators[kind] = jsonschema.Draft202012Validator(schema, registry=registry)
        return check_evidence_ledger(args.evidence_ledger, validators)
    for name, schema in schemas.items():
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as err:
            problems.append(f"{name}: not a valid schema: {err.message}")
    status = jsonschema.Draft202012Validator(schemas["status.schema.json"], registry=registry)
    problems.extend(status_policy_problems(status))
    problems.extend(status_absence_problems(status))
    native_status = jsonschema.Draft202012Validator(schemas["project-status.schema.json"], registry=registry)
    problems.extend(native_status_problems(native_status))
    messages = jsonschema.Draft202012Validator(schemas["messages.schema.json"], registry=registry)
    examples = 0
    for number, line in enumerate((ROOT / "docs" / "writing-a-provider.md").read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("{"):
            continue
        try:
            message = json.loads(line)
        except ValueError:
            problems.append(f"docs/writing-a-provider.md line {number}: not JSON")
            continue
        examples += 1
        for err in messages.iter_errors(message):
            problems.append(f"docs/writing-a-provider.md line {number}: {err.message[:160]}")
            break
    if examples == 0:
        problems.append("docs/writing-a-provider.md: no examples found")
    lock_schema = jsonschema.Draft202012Validator(schemas["lock.schema.json"], registry=registry)
    problems.extend(check_lock_platform_fixtures(lock_schema))
    policy = tomllib.loads((ROOT / "policy.toml").read_text(encoding="utf-8"))
    for err in jsonschema.Draft202012Validator(schemas["policy.schema.json"], registry=registry).iter_errors(policy):
        problems.append(f"policy.toml: {err.message[:160]}")
    evidence = jsonschema.Draft202012Validator(schemas["evidence-record.schema.json"], registry=registry)
    problems.extend(evidence_strength_problems(evidence))
    native_evidence = jsonschema.Draft202012Validator(schemas["project-evidence.schema.json"], registry=registry)
    stage0_evidence = jsonschema.Draft202012Validator(schemas["stage0-evidence.schema.json"], registry=registry)
    problems.extend(native_evidence_problems(native_evidence, stage0_evidence))
    intent_files = 0
    if INTENT_CRITERIA_SCHEMA not in schemas:
        problems.append(f"{INTENT_CRITERIA_SCHEMA}: missing schema")
    else:
        criteria = jsonschema.Draft202012Validator(schemas[INTENT_CRITERIA_SCHEMA], registry=registry)
        intent_files, intent_problems = check_intent_criteria(criteria)
        problems.extend(intent_problems)
    for line in problems:
        print("PROBLEM", line)
    print(json.dumps({"schemas": len(schemas), "examples": examples, "intent_files": intent_files, "problems": len(problems)}))
    return 1 if problems else 0


def native_evidence_problems(validator, stage0) -> list[str]:
    """Distinguish native evidence from the two retained Stage-0 shapes."""
    digest = "sha256:" + "0" * 64
    body = {
        "obligation": "check-one", "core_key": digest, "platform": "linux/x86_64",
        "writer": "fixture", "verdict": "passed", "level": "bounded",
        "strength": {"class": "fixture", "rank": "bounded", "note": "provider annotation"},
        "preimage": {"obligation": digest, "kind": "check",
                     "inputs": {"specified_by": [], "targets": [], "closure": [], "config": digest,
                                "expect": "holds", "tools": []},
                     "provider": {"name": "fixture-checks", "version": "1", "protocol": "0.2"}},
    }
    problems = []
    for verdict in ("passed", "failed"):
        if not validator.is_valid(dict(body, verdict=verdict)):
            problems.append(f"native evidence {verdict}: rejected by project-evidence.schema.json")
    no_strength = dict(body)
    del no_strength["strength"]
    for label, invalid, rule, path in (
        ("missing strength", no_strength, "required", []),
        ("malformed core identity", dict(body, core_key="invalid"), "pattern", ["core_key"]),
        ("nonterminal verdict", dict(body, verdict="unavailable"), "enum", ["verdict"]),
    ):
        errors = list(validator.iter_errors(invalid))
        if len(errors) != 1 or (errors[0].validator, list(errors[0].absolute_path)) != (rule, path):
            problems.append(f"native evidence {label}: expected rejection at {'.'.join(path) or 'the root'}")
    older = dict(body, executor="fixture-executor", summary={"states": 3}, unpinned_tools=[])
    measured = dict(older, tools_measured={"java": {"digest": "0" * 64, "version": "25.0.1"},
                                          "tla2tools": {"digest": "1" * 64, "version": None}})
    for label, retained in (("without measurements", older), ("with measurements", measured)):
        if not stage0.is_valid(retained) or validator.is_valid(retained):
            problems.append(f"stage-0 evidence {label}: must pass only the stage-0 schema")
    missing_executor = dict(measured)
    del missing_executor["executor"]
    invalid_stage0 = (
        ("native body with no helper fields", body, "required", []),
        ("missing executor", missing_executor, "required", []),
        ("unexpected field", dict(measured, unsupported_field={}), "additionalProperties", []),
        ("nonterminal result", dict(older, verdict="unavailable"), "enum", ["verdict"]),
        ("wrong measured digest", dict(older, tools_measured={"java": {"digest": "wrong", "version": "25.0.1"}}),
         "pattern", ["tools_measured", "java", "digest"]),
        ("absent measured version", dict(older, tools_measured={"java": {"digest": "0" * 64}}),
         "required", ["tools_measured", "java"]),
    )
    for label, invalid, rule, path in invalid_stage0:
        if not any((error.validator, list(error.absolute_path)) == (rule, path) for error in stage0.iter_errors(invalid)):
            problems.append(f"stage-0 evidence {label}: expected rejection at {'.'.join(path) or 'the root'}")
    return problems


def native_status_problems(validator) -> list[str]:
    """Native status keeps both its policy source and unresolved project doubts visible."""
    report = {
        "judged": {"kind": "status", "name": "this-project", "self": {"writer": "fixture", "platform": "linux/x86_64"},
                   "policy": {}, "obligations": {}, "intents": {}, "steps": [{"do": {}}]},
        "report": {"obligations": {}, "intents": {}, "project": {"status": "nothing-required"}, "rejected": 0},
        "coverage": {"intents": {}, "thinnest": {}},
        "policy_source": "fixture policy", "ledger": {"entries": 0, "torn": False},
        "not_served": [], "not_checkable": [], "policy_not_applied": [],
        "project_doubts": [], "project_status": "nothing-required",
    }
    problems = []
    for label, valid in (("empty native status", report), ("native refusal", {"refused": "bad-input", "detail": ""})):
        if not validator.is_valid(valid):
            problems.append(f"{label}: rejected by project-status.schema.json")

    output = validator.evolve(schema={"$ref": validator.schema["$id"] + "#/$defs/output"})
    no_policy = dict(report)
    del no_policy["policy_source"]
    negative_entries = dict(report, ledger={"entries": -1, "torn": False})
    pass_with_doubt = dict(report, project_status="passed", project_doubts=["a ledger ends in an entry cut short"])
    for label, invalid, rule, path in (
        ("missing policy source", no_policy, "required", []),
        ("negative ledger count", negative_entries, "minimum", ["ledger", "entries"]),
        ("pass despite a project doubt", pass_with_doubt, "enum", ["project_status"]),
    ):
        errors = list(output.iter_errors(invalid))
        if len(errors) != 1 or (errors[0].validator, list(errors[0].absolute_path)) != (rule, path):
            problems.append(f"native status {label}: expected rejection at {'.'.join(path) or 'the root'}")
    return problems


def status_absence_problems(validator) -> list[str]:
    """No evidence link or act has to be invented to report a supported state."""
    confirmed_empty = {
        "name": "empty", "status": "unguarded",
        "gates": {"hard": 0, "soft": 0, "deferred": 0, "deferred_open": 0},
        "shown": {"level": "none", "weakest_link": None},
        "agreed": {"criteria_confirmed_by": "owner", "checks_matched_by": []},
        "separation": {"weakest": {"level": "self", "source": "declared"},
                       "act": "confirm-baseline", "acts_apart_or_better": 0, "acts_total": 1},
        "exceptions": 0, "score": {"numerator": 0, "denominator": 0},
    }
    draft = dict(confirmed_empty, name="draft", status="draft",
                 agreed={"criteria_confirmed_by": None, "checks_matched_by": []},
                 shown={"level": "none", "weakest_link": "specification-code"},
                 separation={"weakest": {"level": "self", "source": None},
                             "acts_apart_or_better": 0, "acts_total": 1})

    def errors(intent: dict) -> list:
        report = {"status": "0.2", "policy": {"reference": "same"}, "project": {"status": "unknown"},
                  "platforms": [{"os": "linux", "arch": "x86_64"}], "intents": [intent],
                  "obligations": [], "errors": []}
        return list(validator.iter_errors(report))

    problems = []
    for label, intent in (("empty intent without a weakest link", confirmed_empty), ("draft without an act", draft)):
        found = errors(intent)
        if found:
            problems.append(f"status {label}: {found[0].message}")

    sampled = deepcopy(confirmed_empty)
    sampled["shown"]["level"] = "sampled"
    recorded = deepcopy(draft)
    recorded["separation"]["act"] = "confirm-baseline"
    stronger = deepcopy(draft)
    stronger["separation"]["weakest"]["level"] = "apart"
    for label, intent, field in (
        ("sampled assurance without a weakest link", sampled, ["shown", "weakest_link"]),
        ("recorded act without a fact source", recorded, ["separation", "weakest", "source"]),
        ("strong separation without a fact source", stronger, ["separation", "weakest", "source"]),
    ):
        found = errors(intent)
        if len(found) != 1 or list(found[0].absolute_path) != ["intents", 0, *field]:
            problems.append(f"status {label}: expected rejection for {'.'.join(field)}")
    return problems


def status_policy_problems(validator) -> list[str]:
    """A project pass names its policy. A project with no policy can report nothing required."""
    platform = {"os": "linux", "arch": "x86_64"}
    passing = {
        "status": "0.2", "policy": {"reference": "same", "identity": "sha256:" + "0" * 64},
        "project": {"status": "passed"}, "platforms": [platform], "intents": [], "errors": [],
        "obligations": [{"binding": "widths", "name": "width/docs/intro.txt", "platform": platform,
                         "status": "passed", "strength": {"class": "fixture", "rank": "sampled"},
                         "non_vacuous": "none-planted", "isolation": "none", "trusted_base": []}],
    }
    missing_identity = dict(passing, policy={"reference": "same"})
    no_policy = dict(passing, policy={"reference": "unavailable"},
                     project={"status": "nothing-required"}, obligations=[])
    problems = []
    for label, report in (("passed with a policy identity", passing), ("nothing-required without a policy", no_policy)):
        errors = list(validator.iter_errors(report))
        if errors:
            problems.append(f"status {label}: {errors[0].message}")
    errors = list(validator.iter_errors(missing_identity))
    if not errors:
        problems.append("status passed without a policy identity: accepted")
    elif not (len(errors) == 1 and errors[0].validator == "required" and list(errors[0].absolute_path) == ["policy"]
              and errors[0].validator_value == ["identity"]):
        problems.append(f"status passed without a policy identity: rejected for the wrong reason ({errors[0].message})")
    return problems


if __name__ == "__main__":
    sys.exit(main())
