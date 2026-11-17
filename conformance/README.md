# Conformance kit

What a correct kernel must do, written as data, before any kernel exists. The kit judges a kernel; it is not one. This is stage 1 of [the bootstrap](../ARCHITECTURE.md#8-building-dodona-with-dodona).

Version 0 covers what the formal models cover and no more: how an obligation's status follows from recorded results, and how an intent's status follows from its gates, its confirmation and its exceptions. [`spec/CLAIMS.md`](../spec/CLAIMS.md) lists what is not modelled, and therefore not in the kit.

## What is here

| Path | Holds |
|---|---|
| `kernel/evidence/` | Scenarios for obligation status: edits, tool changes, submissions, completions, lost runs, an unreachable backend |
| `kernel/intent/` | Scenarios for intent status: confirmation, checks, direct edits, exceptions with their separation level, policy floors |
| `kernel/index.json` | The modelled cases that have no scenario, each with the reason |
| `vectors/canonical.json` | The [canonical encoding](../protocol/canonical-encoding.md): values with their exact text and hash, and inputs that must be refused |
| `vectors/paths.json` | The [path check](../protocol/path-check.md): accepted paths, refused paths with the reason, and sets that collide |

Every scenario names the claim it bears on and the model cases it covers. Each planted defect in the formal models has at least one scenario that a kernel repeating that defect fails. The repository checks enforce this.

## How a kernel is judged

`tools/run_kit.py -- <kernel command>` starts the kernel once per scenario, with the scenario as JSON on standard input. The kernel prints `{"results": [...]}` with one result per step. A scenario matches when every field its steps expect is present and equal. A crash, a timeout or anything else is a mismatch.

### Evidence scenarios

A scenario gives the obligations with what each depends on, the starting content of every definition, the starting tool, and whether the backend is up. Content and tools are opaque strings standing for identities.

| Step | Meaning |
|---|---|
| `{"edit": {"definition": D, "to": H}}` | The content of definition D becomes H |
| `{"repin": {"to": T}}` | The pinned tool becomes T |
| `{"backend": {"to": "up" or "down"}}` | The execution backend becomes reachable or unreachable |
| `{"submit": {"obligation": O, "as": J}}` | A check of O is asked for. With the backend up, run J starts on the inputs as they are now. With it down, the outcome is `unavailable` and no run exists |
| `{"complete": {"run": J, "verdict": "passed" or "failed"}}` | Run J finishes with that verdict for the inputs it was given |
| `{"lose": {"run": J}}` | Run J ends with no result |

The result after each step is an object with one entry per obligation: `{"status": S}` and, when the status is `unknown`, `"reason": R`.

- `status` is `passed`, `failed`, `conflict` or `unknown`, by the rule in [the data model](../MODEL.md#4-status). Only results recorded for the current inputs count: the content of everything the obligation depends on, and the tool.
- `reason` is `pending` if a run on the current inputs is in flight; otherwise the outcome of the most recent attempt on the current inputs that left no result, `unavailable` or `error`; otherwise `never-run`.
- Recorded results take precedence over a run in flight: an obligation that has passed stays `passed` while it is being checked again.

### Intent scenarios

A scenario gives the criteria with their gates as first written, and a policy: `exception_separation`, the least separation at which an exception takes effect, and `min_hard_gates`.

| Step | Meaning |
|---|---|
| `{"confirm": {}}` | The owner confirms the gates as they stand |
| `{"check": {"criterion": C, "status": S}}` | The check behind C now has status S: `unknown`, `passed`, `failed` or `conflict` |
| `{"edit": {"criterion": C, "to": G}}` | The gate of C is changed directly, not by an exception |
| `{"amend": {"criterion": C, "to": G, "by": "owner" or "worker", "separation": L}}` | An exception is asked for. `separation` is the level on record, and may be absent |

The result after each step has `"status"`, and after an `amend` step also `"amendment": {"takes_effect": true or false, "level": L}`.

- `level` is the separation the kernel works out: `self` if the worker is the grantor or nothing is recorded, otherwise the level on record.
- An exception takes effect only if the owner granted it and its level is at or above the policy floor. The levels in order are `self`, `helper`, `apart`, `tested`, `cross-make`, `credentialed`.
- `status` is the first of these that applies: `draft` if the owner has not confirmed, or a gate was edited since; `unguarded` if there are fewer hard gates than `min_hard_gates`; `open` if any hard gate's check is not `passed`; `fulfilled` if every deferred gate's check is `passed` too; otherwise `delivered`.

Version 0 leaves out `uncovered` and `overdue`: every criterion has a check, and there is no clock.

## Rules for the kit

- A scenario is added before the behaviour it tests, and is committed before any kernel that will be judged by it.
- Expected results are written by hand from the documents and the models, never produced by a kernel.
- Two kernels that both pass the whole kit and still disagree on some input mean the kit is missing a scenario; the disagreement becomes one.
- Hostile names and bytes are stored as escaped data inside the vectors, never as real files, so the kit can be checked out on every platform.

## Not yet in the kit

- Scenarios for providers: malformed messages, late answers, a deliberately misbehaving provider.
- Kit adequacy: running kernels with known defects against the kit and reporting the fraction it rejects.
- Anything not modelled: the planner, artifacts, platforms, the ledger's crash behaviour, child intents, time limits, varying checks, attempts and tickets.
