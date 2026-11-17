"""What a finished run of the model checker shows. The one place that reads its output.

Used by the provider, and by tools/check_models.py, so the two cannot disagree.
"""
from __future__ import annotations

import re

NO_ERROR = "Model checking completed. No error has been found."


def judge(case: dict, exit_code: int | None, output: str) -> dict:
    """Decide whether one finished case matches its expectation."""
    want = case["expect"]
    result = {"config": case["config"], "expected": want, "exit": exit_code}
    if exit_code is None:
        return {**result, "outcome": "did-not-run", "match": False}
    if want == "temporal-violation":
        ok = exit_code == case["expect_exit"] and "Temporal properties were violated." in output
        outcome = "temporal violation" if ok else ("no-violation" if NO_ERROR in output else "did-not-complete")
        return {**result, "outcome": outcome, "match": ok}
    if want == "no-violation":
        complete = NO_ERROR in output and ", 0 states left on queue." in output
        ok = exit_code == case["expect_exit"] and complete
        outcome = "no-violation" if ok else "did-not-complete"
        if "is violated" in output or "were violated" in output:
            outcome = "violation"
        return {**result, "outcome": outcome, "match": ok}
    # The checker words a violation found in the very first state differently.
    named = re.compile(rf"Invariant {re.escape(case['of'])} is violated(\.| by the initial state:)")
    if exit_code == case["expect_exit"] and named.search(output):
        return {**result, "outcome": f"violation of {case['of']}", "match": True}
    if "is violated" in output:
        outcome = "violation of a different property"
    elif NO_ERROR in output:
        outcome = "no-violation"
    else:
        outcome = "did-not-complete"
    return {**result, "outcome": outcome, "match": False}
