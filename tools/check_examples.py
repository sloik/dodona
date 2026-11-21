"""Validate the schemas, guide examples, policy, project criteria and draft lock fixtures.

    python tools/check_examples.py

Stage-0 helper (decision 0023). Unlike the other helpers this one needs a
third-party package, `jsonschema`, because a JSON Schema validator is not in
the standard library. It runs in CI with a pinned version. Without the package
it says so and fails: a check that silently does nothing is not a check.
Three status controls exercise the draft requirement that a project pass names its policy.

Exit status is 0 only if the schemas, examples, policy and project criteria validate.
The evidence-strength, status-policy, project criteria and draft lock controls
must also give the expected results.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
INTENT_CRITERIA_SCHEMA = "project-intent-criteria.schema.json"


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


def main() -> int:
    try:
        import jsonschema
        from referencing import Registry, Resource
    except ImportError:
        print("the jsonschema package is not installed; nothing was checked")
        return 1
    problems = []
    registry = Registry()
    schemas = {}
    for path in sorted((ROOT / "protocol").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as err:
            problems.append(f"{path.name}: not a valid schema: {err.message}")
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        schemas[path.name] = schema
    status = jsonschema.Draft202012Validator(schemas["status.schema.json"], registry=registry)
    problems.extend(status_policy_problems(status))
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
