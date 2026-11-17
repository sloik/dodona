# Conformance kit

What a correct kernel must do, written as data, before any kernel exists. The kit judges a kernel; it is not one. This is stage 1 of [the bootstrap](../ARCHITECTURE.md#8-building-dodona-with-dodona).

It covers what the formal models cover and no more: obligation status, intent status with exceptions and separation, what the planner reruns, the shown level and non-vacuity, parents and children, repeated attempts, platforms, and decisions flagged on change. [`spec/CLAIMS.md`](../spec/CLAIMS.md) lists what is not modelled, and therefore not in the kit.

## What is here

| Path | Holds |
|---|---|
| `kernel/evidence/` | Scenarios for obligation status: edits, tool changes, submissions, completions, lost runs, an unreachable backend |
| `kernel/intent/` | Scenarios for intent status: confirmation, checks, direct edits, exceptions with their separation level, policy floors |
| `kernel/plan/` | What is planned to run after edits and tool changes, with per-definition and file-level identity |
| `kernel/assurance/` | The shown level from the evidence links, and whether a check is shown able to fail |
| `kernel/tree/` | A parent intent with children |
| `kernel/attempts/` | Trying a judgement again |
| `kernel/platforms/` | Results on more than one platform |
| `kernel/decisions/` | A decision flagged when what it governs changes |
| `kernel/index.json` | The modelled cases that have no scenario, each with the reason |
| `provider/misbehaving_provider.py` | A provider that does one thing wrong in each of its modes: garbage, a byte-order mark, a carriage return, bad encoding, an over-long line, half a line, no answer, a late answer, a wrong or repeated answer, a flood on standard error, a process left behind |
| `provider/cases.json` | What a host must do with it in each mode |
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
| `{"amend": {"criterion": C, "to": G, "by": "owner" or "worker", "claims": L, "source": "declared" or "attested"}}` | An exception is asked for. `claims` is the separation level the record claims and may be absent. `source` says who stands behind the claim and is `declared` when absent |

The result after each step has `"status"`, and after an `amend` step also `"amendment": {"takes_effect": true or false, "level": L}`.

- `level` is the separation the kernel grants. It is `self` if the worker is the grantor or nothing is claimed. Otherwise it is the claimed level, capped by its source: a `declared` claim earns `helper` at most, an `attested` one `cross-make` at most.
- An exception takes effect only if the owner granted it and its level is at or above the policy floor. The levels in order are `self`, `helper`, `apart`, `tested`, `cross-make`, `credentialed`.
- `status` is the first of these that applies: `draft` if the owner has not confirmed, or a gate was edited since; `unguarded` if there are fewer hard gates than `min_hard_gates`; `open` if any hard gate's check is not `passed`; `fulfilled` if every deferred gate's check is `passed` too; otherwise `delivered`.

`uncovered` and `overdue` are left out: every criterion has a check, and there is no clock.

### Plan scenarios

A scenario gives `definitions`, each with what it `depends_on` and the `file` it is in; a `granularity`, `definition` or `file`; `obligations`; and the starting content of each definition and each tool. An obligation either has `targets` (definitions) and perhaps a `tool`, or is `artifact_of` another obligation, meaning it works on what that obligation produces, with a `tool` of its own.

| Step | Meaning |
|---|---|
| `{"edit": {"definition": D, "to": H}}` | The content of D becomes H |
| `{"repin": {"tool": T, "to": H}}` | Tool T becomes H |
| `{"run": {"obligation": O}}` | O is run, if it is planned and, where it works on another obligation's product, that other obligation has a result for the current inputs. Otherwise nothing happens |

The result after each step has `"plan"`: the names of the obligations with no result for their current inputs, sorted. After a `run` step it also has `"ran"`, true or false.

- An obligation's inputs are the content of its targets and of everything they depend on, however indirectly, and its tool if it has one. An obligation that is `artifact_of` another has that other's inputs as well as its own tool.
- With granularity `file`, the content of a definition counts as the content of every definition in the same file.
- A result is kept for the inputs it was run on, and counts again whenever the inputs are the same again.

### Assurance scenarios

Each step is `{"judge": {"links": {...}, "defects": {...}}}`. `links` gives a level for some or all of `spec-to-code`, `code-to-runs` and `runs-to-world`; a link that is absent or null was not reported. `defects` gives the status of each planted defect of a check: `passed`, `failed` or `unknown`.

The result has `"shown"`: the weakest of the three links, on the scale `none`, `asserted`, `observed`, `sampled`, `bounded`, `proven`, where a link not reported counts as `none`. It also has `"non_vacuous"`: `none-planted` if there are no defects, `shown` if every one is `passed`, otherwise `not-shown`.

### Tree scenarios

A scenario gives a `root` and `children`, each with the gate of its one criterion, `hard` or `soft`, and a policy with `min_hard_gates`.

| Step | Meaning |
|---|---|
| `{"confirm": {}}` | The owner confirms the tree as it stands |
| `{"check": {"node": N, "status": S}}` | The check behind N's criterion now has status S. N is `root` or a child |
| `{"edit": {"node": N, "to": G}}` | N's gate is changed directly |
| `{"remove": {"child": K}}` | Child K is removed |
| `{"add": {"child": K, "gate": G}}` | Child K is added, its check unknown |

The result has `"status"`, the first of these that applies: `draft` if the owner has not confirmed, or anything was edited, added or removed since; `unguarded` if the whole tree has fewer hard gates than `min_hard_gates`; `open` if any hard gate's check is not `passed`, or any child has no hard gate; otherwise `delivered`.

### Attempts scenarios

| Step | Meaning |
|---|---|
| `{"take": {"as": T}}` | A ticket T is taken for an attempt at judging the current target. The attempt is open |
| `{"close": {"ticket": T, "result": "agreed" or "refused"}}` | The attempt is closed with that result |
| `{"change_target": {}}` | The thing being judged changes |

The result has four fields, worked out from the attempts on the current target, in the order they were taken.

- `"result"`: `none` if there are none; `agreed` if every one is closed as agreed; otherwise `refused`. An open attempt counts as a failure.
- `"shopped"`: true if some attempt closed as agreed was taken after one that is not agreed.
- `"cap"`: `helper` when shopped, otherwise null.
- `"attempts"`: how many tickets have been taken in all, across changes of target.

### Platforms scenarios

A scenario gives `keys` (sets of inputs), `platforms`, and whether policy allows a record from one platform to stand in for another, `stand_in_allowed`. Each step is `{"record": {"key": K, "platform": P, "verdict": "passed" or "failed"}}`.

- `"status"`, by key then platform: the platform's own verdict if it has one; otherwise another platform's verdict for the same key, if standing in is allowed and the claim is verified; otherwise `unknown`. The claim is verified when some key has the same verdict on two platforms and no key has different verdicts on two platforms.
- `"stood_in"`: the sorted list of `[key, platform]` pairs whose status rests on another platform's record.
- `"reproducibility"`, by key: `failed` if two platforms differ, `passed` if two agree, otherwise `unknown`.

### Decisions scenarios

A scenario gives `names` with their starting content and the name a decision `governs`. The decision records the content its name had at the start.

| Step | Meaning |
|---|---|
| `{"edit": {"name": N, "to": H}}` | The content behind N becomes H. A null H means N no longer exists |
| `{"review": {}}` | The decision is reviewed against what its name is now. If the name no longer exists, nothing happens |

The result has `"flagged"`: true exactly when the content behind the governed name is not the content the decision recorded.

## How a host is judged

`tools/run_provider_cases.py -- <host command>` starts the host once per case and has it run the misbehaving provider in that mode. A case matches when the host reports the expected outcome and reason, returns within the deadline plus a grace period, and nothing the provider started is still running. The first case is a well-behaved provider that must be accepted: a host that refuses everything would otherwise pass.

`tools/provider_host.py` is a small reference host, there to show the session rules can be kept on macOS, Linux and Windows. It checks framing, encoding, line length, deadlines and message envelopes, and ends every process the provider started. It does not validate message bodies against the schemas, and it is not part of any kernel yet.

## Rules for the kit

- A scenario is added before the behaviour it tests, and is committed before any kernel that will be judged by it.
- Expected results are written by hand from the documents and the models, never produced by a kernel.
- Two kernels that both pass the whole kit and still disagree on some input mean the kit is missing a scenario; the disagreement becomes one.
- Hostile names and bytes are stored as escaped data inside the vectors, never as real files, so the kit can be checked out on every platform.

## Not yet in the kit

- Messages that are well-formed and wrong in content: a verdict with no run behind it, a result that fails its schema. The reference host does not validate bodies.
- Kit adequacy: running kernels with known defects against the kit and reporting the fraction it rejects.
- Anything not modelled: the ledger's crash behaviour, time limits, varying checks, executors, the lock, more than one level of child intents.
- How a claim's source is established. The scenarios give `declared` or `attested` as an input; working it out from an act record is not in the kit.
