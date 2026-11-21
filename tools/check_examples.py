"""Validate the schemas, provider guide examples, draft lock fixtures and dodona's policy.

    python tools/check_examples.py

Stage-0 helper (decision 0023). Unlike the other helpers this one needs a
third-party package, `jsonschema`, because a JSON Schema validator is not in
the standard library. It runs in CI with a pinned version. Without the package
it says so and fails: a check that silently does nothing is not a check.
Three status controls exercise the draft requirement that a project pass names its policy.

Exit status is 0 only if every schema is valid, every JSON line in
docs/writing-a-provider.md is a valid message, and policy.toml is a valid policy.
The draft lock fixtures must also give the expected result.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent


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
    for line in problems:
        print("PROBLEM", line)
    print(json.dumps({"schemas": len(schemas), "examples": examples, "problems": len(problems)}))
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
