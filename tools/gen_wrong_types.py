"""Writes the kit scenarios in which steps carry values of the wrong type. Stage-0 helper (decision 0023).

    python tools/gen_wrong_types.py          # write the files
    python tools/gen_wrong_types.py --check  # fail if they differ from what is on disk

The rule (conformance/README.md): a step that carries a value of another type
than the tables give changes nothing. So each scenario here is an existing
scenario with, after some of its steps, the same step again with one value
replaced by one of the wrong type; what is expected after it is exactly what
was expected after the step it copies. No expected value is made up: each is
taken from the scenario as its author wrote it.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
KIT = ROOT / "conformance" / "kernel"
SOURCES = ["attempts/clean_agreement", "evidence/failure_then_fix", "plan/file_identity_costs_a_rerun",
           "tree/removing_a_child_returns_to_draft", "intent/declared_claim_is_capped_at_helper", "decisions/edit_flags_and_review_clears"]
ODD = [0, False, None, [], {}, 7]


def strings(value, path=()):
    """Every place in a step that holds a string, as a path of keys."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield from strings(inner, path + (key,))
    elif isinstance(value, str):
        yield path


def put(value, path, new):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = new


def variant(source: dict) -> dict:
    steps, number = [], 0
    for step in source["steps"]:
        steps.append(step)
        places = list(strings(step["do"]))
        if not places:
            continue
        for place in places:  # one copy for each value the step holds
            odd = copy.deepcopy(step)
            put(odd["do"], place, ODD[number % len(ODD)])
            number += 1
            # The copy changes nothing, so what was true after the step it copies is still true.
            # A field that reports what the step itself did (`ran`, `amendment`) is not carried over.
            odd["expect"] = {k: v for k, v in step["expect"].items() if k not in ("ran", "amendment")}
            if odd["expect"]:
                steps.append(odd)
    name = source["name"] + "_with_values_of_the_wrong_type"
    return {**{k: v for k, v in source.items() if k not in ("name", "why", "covers", "steps")}, "name": name, "covers": [],
            "why": f"The scenario {source['name']}, with after each step the same step again, once for each value it holds, with that value of the wrong type. "
                   "Such a step changes nothing, so what was expected after the step it copies is expected after it too.",
            "steps": steps}


def main() -> int:
    check, stale, written = "--check" in sys.argv, [], 0
    for name in SOURCES:
        path = KIT / f"{name}.json"
        if not path.exists():
            print(f"no scenario {name}")
            return 1
        made = variant(json.loads(path.read_text(encoding="utf-8")))
        target = path.with_name(made["name"] + ".json")
        text = json.dumps(made, indent=2) + "\n"
        if check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                stale.append(str(target.relative_to(ROOT)))
        else:
            target.write_text(text, encoding="utf-8")
            written += 1
    if stale:
        print("not what tools/gen_wrong_types.py writes:", ", ".join(stale))
        return 1
    print(f"{len(SOURCES)} files {'checked' if check else 'written'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
