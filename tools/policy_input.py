"""The policy as a status command takes it, made from the policy file (decision 0034). Stage-0 helper.

    python tools/policy_input.py POLICY.toml     # prints the policy in the form the status command takes
    python tools/policy_input.py --self-test     # plants a fault for each rule; each must be caught

The full policy is checked against protocol/policy.schema.json first: a policy that does not fit it is refused,
so a misspelt field is never read as no field. Then it is reduced to what the status rules apply, the intents
required, the least number of hard gates and the floors (with the defaults the schema gives), and every other
field the policy holds is named in `not_applied`, so that a reader of the status sees what was not applied and a
project holding such fields is never reported as passed. Validating needs the `jsonschema` package; without it
this refuses, which is never a pass.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The floors the schema gives when the policy leaves a kind out (decision 0024).
FLOOR_DEFAULTS = {"grant-amendment": "apart", "change-policy": "apart", "close-deferred": "helper"}
# What the status rules apply. Every other field present is named in not_applied.
APPLIED = {("policy",), ("reference",), ("required", "intents"), ("gates", "min_hard"),
           ("separation", "floor", "confirm-baseline", "level"), ("separation", "floor", "grant-amendment", "level")}


def sort_key(text: str) -> list[int]:
    return list(text.encode("utf-16-be"))


class NotValid(Exception):
    pass


def validate(policy: dict) -> None:
    try:
        import jsonschema
        import referencing
    except ImportError:
        raise NotValid("the jsonschema package is needed to check the policy against its schema") from None
    registry = referencing.Registry()
    for path in (ROOT / "protocol").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], referencing.Resource.from_contents(schema))
    schema = json.loads((ROOT / "protocol" / "policy.schema.json").read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema, registry=registry).iter_errors(policy), key=lambda e: list(e.path))
    if errors:
        raise NotValid(f"the policy does not fit policy.schema.json: {'/'.join(map(str, errors[0].path))}: {errors[0].message}")


def leaves(value, path=()):
    """The paths of the fields a policy holds: a list or a scalar is one field, an object is its fields."""
    if isinstance(value, dict) and value:
        for key, inner in value.items():
            yield from leaves(inner, path + (key,))
    elif path:
        yield path


def reduce(policy: dict) -> dict:
    floors = dict(FLOOR_DEFAULTS)
    floors.update({kind: entry["level"] for kind, entry in policy.get("separation", {}).get("floor", {}).items()})
    not_applied = sorted({".".join(p) for p in leaves(policy) if p not in APPLIED}, key=sort_key)
    return {"required": policy.get("required", {}).get("intents", []), "min_hard_gates": policy.get("gates", {}).get("min_hard", 1),
            "floors": floors, "not_applied": not_applied}


def self_test() -> list[str]:
    problems = []
    good = {"policy": "0.2", "required": {"intents": ["i1"], "obligations": [{"binding": "b", "name": "o"}]},
            "gates": {"min_hard": 2, "max_deferred_days": 30}, "separation": {"floor": {"confirm-baseline": {"level": "apart"}}}}
    try:
        validate(good)
    except NotValid as err:
        problems.append(f"a policy that fits the schema is refused: {err}")
    for name, bad in (("a misspelt floor kind", {"policy": "0.2", "separation": {"floor": {"confirm_baseline": {"level": "apart"}}}}),
                      ("a misspelt gate", {"policy": "0.2", "gates": {"min-hard": 5}}),
                      ("a level not on the scale", {"policy": "0.2", "separation": {"floor": {"match-check": {"level": "Apart"}}}}),
                      ("no version", {"required": {"intents": ["i1"]}}),
                      ("required obligations given as text", {"policy": "0.2", "required": {"obligations": "o1"}})):
        try:
            validate(bad)
            problems.append(f"{name} is accepted")
        except NotValid:
            pass
    reduced = reduce(good)
    want = {"required": ["i1"], "min_hard_gates": 2,
            "floors": {"grant-amendment": "apart", "change-policy": "apart", "close-deferred": "helper", "confirm-baseline": "apart"},
            "not_applied": ["gates.max_deferred_days", "required.obligations"]}
    if reduced != want:
        problems.append(f"the reduced policy is {reduced}, not {want}")
    if reduce({"policy": "0.2"}) != {"required": [], "min_hard_gates": 1, "floors": dict(FLOOR_DEFAULTS), "not_applied": []}:
        problems.append("an empty policy does not reduce to its defaults")
    if reduce({"policy": "0.2", "x-note": "hi"})["not_applied"] != ["x-note"]:
        problems.append("an x- field is not named as not applied")
    return problems


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        try:
            problems = self_test()
        except NotValid as err:
            print(f"COULD NOT RUN {err}")
            return 2
        for p in problems:
            print("PROBLEM", p)
        print("policy input:", "FAILED" if problems else "every planted fault caught")
        return 1 if problems else 0
    try:
        policy = tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
        validate(policy)
    except (OSError, tomllib.TOMLDecodeError, NotValid) as err:
        print(json.dumps({"refused": "bad-policy", "detail": str(err)}))
        return 1
    print(json.dumps(reduce(policy), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
