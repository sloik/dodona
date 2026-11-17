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
| `kernel/acts/` | How separate the party behind an act was, from the record of it, with real keyed signatures |
| `kernel/status/` | What a kernel reports about a whole project from its ledger |
| `ledger/cases.json` | The exact bytes of a ledger, and every way of damaging it |
| `vectors/core-key.json` | The key of an evidence record from the inputs it states |
| `kernel/index.json` | The modelled cases that have no scenario, each with the reason |
| `provider/misbehaving_provider.py` | A provider that does one thing wrong in each of its modes: garbage, a byte-order mark, a carriage return, bad encoding, an over-long line, half a line, no answer, a late answer, a wrong or repeated answer, a flood on standard error, a process left behind |
| `provider/cases.json` | What a host must do with it in each mode |
| `vectors/canonical.json` | The [canonical encoding](../protocol/canonical-encoding.md): values with their exact text and hash, and inputs that must be refused |
| `vectors/paths.json` | The [path check](../protocol/path-check.md): accepted paths, refused paths with the reason, and sets that collide |

Every scenario names the claim it bears on and the model cases it covers. Each planted defect in the formal models has at least one scenario that a kernel repeating that defect fails. The repository checks enforce this.

## How a kernel is judged

`tools/run_kit.py -- <kernel command>` starts the kernel once per scenario, with the scenario as JSON on standard input. The kernel is shown what happens in each step and nothing else: the expected results and the notes about the scenario are removed first. The kernel prints `{"results": [...]}` with one result per step. A scenario matches when every field its steps expect is present and equal. A crash, a timeout or anything else is a mismatch.

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
- An exception takes effect only if the owner granted it and its level is at or above the policy floor. The levels in order are `self`, `helper`, `apart`, `tested`, `cross-make`, `credentialed`. An exception that takes effect is the owner's own act and leaves the intent confirmed.
- A soft gate never affects the status, whatever its check says.
- `min_hard_gates` is at least 1. A lower value is treated as 1.
- An `edit` that sets a gate to what it already is changes nothing.
- `status` is the first of these that applies: `draft` if the owner has not confirmed, or a gate was edited since; `unguarded` if there are fewer hard gates than `min_hard_gates`; `open` if any hard gate's check is not `passed`; `delivered` if any deferred gate's check is not `passed`; otherwise `fulfilled`. An intent with no deferred gate is therefore fulfilled as soon as it is delivered.

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
- With granularity `file`, the content of a definition counts as the content of every definition in the same file. Only the targets and what they depend on are followed; what a file-mate depends on is not.
- An obligation may be `artifact_of` one that is itself `artifact_of` another.
- A result is kept for the inputs it was run on, and counts again whenever the inputs are the same again.

### Assurance scenarios

Each step is `{"judge": {"links": {...}, "defects": {...}}}`. The scale, weakest first, is `none`, `asserted`, `observed`, `sampled`, `bounded`, `proven`. `links` gives a level for some or all of `spec-to-code`, `code-to-runs` and `runs-to-world`; a link that is absent or null was not reported. `defects` gives the status of each planted defect of a check: `passed`, `failed` or `unknown`.

The result has `"shown"`: the weakest of the three links, on the scale `none`, `asserted`, `observed`, `sampled`, `bounded`, `proven`, where a link not reported counts as `none`. It also has `"non_vacuous"`: `none-planted` if there are no defects, `shown` if every one is `passed`, otherwise `not-shown`.

### Tree scenarios

A scenario gives a `root` and `children`, each with the gate of its one criterion, `hard` or `soft`, and a policy with `min_hard_gates`. There may be no children. Adding a child that is already there, or setting a gate to what it already is, changes nothing.

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

A scenario may give `claims`, the separation level the act claims. Closing a ticket that was never taken, or is already closed, changes nothing. A ticket taken before a change of target can still be closed.

The result has these fields. The first three are worked out from the attempts on the current target, as they stand now, in the order they were taken.

- `"result"`: `none` if there are none; `agreed` if every one is closed as agreed; otherwise `refused`. An open attempt counts as a failure.
- `"shopped"`: true if some attempt closed as agreed was taken after one that is not agreed.
- `"cap"`: `helper` when shopped, otherwise null.
- `"attempts"`: how many tickets have been taken in all, across changes of target.
- `"retried"`: true if, among all attempts across changes of target, some attempt closed as agreed was taken after one that is not agreed.
- `"granted"`, when the scenario gives `claims`: the claimed level, lowered to `helper` if the cap applies and the claim was higher. The cap never raises a level.

### Platforms scenarios

A scenario gives `keys` (sets of inputs), any number of `platforms`, whether policy allows a record from one platform to stand in for another, `stand_in_allowed`, and whether the provider claims its results do not depend on the platform, `provider_claims`, true when absent. Each step is `{"record": {"key": K, "platform": P, "verdict": "passed" or "failed"}}`. A second record for the same key and platform with the same verdict changes nothing; with the other verdict it makes that platform's own status `conflict`.

- `"status"`, by key then platform: the platform's own verdict if it has one, or `conflict`; otherwise another platform's verdict for the same key, if standing in is allowed, the provider claims platform independence, and the claim is verified; otherwise `unknown`. The claim is verified when some key has the same verdict on at least two platforms, whether passed or failed, and no key has different verdicts anywhere. When a stand-in is allowed all of a key's verdicts are the same, so it does not matter which platform's is taken.
- `"stood_in"`: the list of `[key, platform]` pairs whose status rests on another platform's record, sorted by key and then platform.
- `"reproducibility"`, by key: `differs` if the key has both verdicts recorded, on one platform or several; `agrees` if at least two platforms have a verdict and all are the same; otherwise `unknown`.

### Decisions scenarios

A scenario gives `names` with their starting content and the list of names a decision `governs`. The decision records the content each governed name had at the start.

| Step | Meaning |
|---|---|
| `{"edit": {"name": N, "to": H}}` | The content behind N becomes H. A null H means N no longer exists |
| `{"review": {}}` | The decision is reviewed against what its names are now, and records that. If any governed name no longer exists, nothing happens |

The result has `"flagged"`: true exactly when the content behind some governed name is not the content the decision recorded for it. Only a review changes what is recorded.

### Acts scenarios

How separate was the party behind an act of judgement ([decision 0024](../decisions/0024-separation-is-graded-not-enforced.md)). A scenario gives a `policy` with `attestors`, a map from key name to a key in hexadecimal, and `makes`, a list of groups of `vendor/family` names that count as the same make. Each step is `{"grade": R}` where R is an act record ([schema](../protocol/act-record.schema.json)). The keys in the kit are fixtures, public by design.

The result has `"claims"`, the level the record's facts would support if they were all true; `"level"`, the level granted; and `"source"`, `attested` if the granted level is above `helper` and otherwise `declared`.

The facts:

| Fact | Holds when | Reads |
|---|---|---|
| distinct | `actor.id` is not `worker.id`, and `actor.session` is not `worker.session` | `actor`, `worker` |
| started | `actor.started_by` is present and is not `worker.id` | `actor`, `worker` |
| briefed | `brief.issued_by` is `kernel` or `owner` | `brief` |
| given | `given` is present and not empty, and every item's role is `work`, `criteria`, `brief`, `known-wrong` or `known-right` | `given` |
| fresh | `fresh_context` is true | `fresh_context` |
| kept | `transcript` is present | `transcript` |
| tested | `known_bad.supplied_by` is `kernel` or `owner`; `rejected_wrong` and `accepted_right` are both true; and `given` holds an item with role `known-wrong` and content `known_bad.wrong`, and one with role `known-right` and content `known_bad.right` | `known_bad`, `given` |
| other make | `actor.make` and `worker.make` both give `vendor` and `family`, both `vendor/family` names appear in `makes`, and they are in different groups | `actor`, `worker` |

`claims` is `self` if distinct does not hold; otherwise `helper`; `apart` if started, briefed, given, fresh and kept also hold; `tested` if tested holds as well; `cross-make` if other make holds as well. Each level needs every fact of the levels below it.

A fact is **vouched for** when every field it reads is listed in `attestation.covers`, `attestation.key` names a key in `attestors`, and `attestation.mac` is the HMAC-SHA256, under that key, of the canonical encoding of `{"covers": C, "fields": F}`, where C is `covers` and F holds each covered field of the record under its name. `mac` is lowercase hexadecimal. A record with no attestation, a key the policy does not name, or a mac that does not match, has no fact vouched for.

`level` is the highest level, not above `claims`, that is `self` or `helper`, or all of whose facts and the facts of the levels below it are vouched for. `credentialed` is never granted.

### Status scenarios

What a kernel reports about a whole project. A scenario gives:

- `self`: this kernel's `writer` name and its `platform`.
- `policy`: `min_hard_gates`; `required`, the intents that must be delivered; `trusted_writers`; `floors`, the least separation at which an act of each kind counts; and `attestors` and `makes` as in acts scenarios.
- `obligations`: for each name, the `preimage` of its core key as things stand ([vectors](vectors/core-key.json)).
- `intents`: for each id, its `owner`, its `worker`, its `children`, and its `criteria`, each with a `gate` and `checked_by`, a list of obligation names.

| Step | Meaning |
|---|---|
| `{"append": {"kind": "evidence", "body": B}}` | A record is added to the ledger. B has `obligation`, `preimage`, `core_key`, `platform`, `verdict` and `writer` |
| `{"append": {"kind": "act", "body": R}}` | An act record is added to the ledger |
| `{"change": {"obligation": O, "preimage": P}}` | The inputs of O are now P |
| `{"set_gate": {"intent": I, "criterion": C, "to": G}}` | A gate is edited directly |

The result has `obligations`, `intents`, `project` and `rejected`.

**Obligations.** An evidence record is *rejected* if its `core_key` is not the identity of its own `preimage`; `rejected` is how many such records the ledger holds. A record that is not rejected *counts* for its obligation when its writer is this kernel or one of `trusted_writers`, its platform is this kernel's, and its `core_key` is the identity of the obligation's preimage as things stand. An obligation is `passed` if records count and all are passed, `failed` if all are failed, `conflict` if they differ, and otherwise `unknown` with `"reason": "never-run"`.

**Baseline.** The baseline of an intent is the identity of `{"owner": O, "children": [sorted], "criteria": {C: {"gate": G, "checked_by": [sorted]}}}`.

**Acts.** An act record is graded as in acts scenarios, with one more rule: if its `worker.id` is not the intent's `worker`, its level is `self`. An intent is *confirmed* when the ledger holds an act of kind `confirm-baseline` whose `lineage.intent` is the intent, whose `result` is `agreed`, whose `target` is the intent's baseline as things stand, whose `actor.id` is the intent's owner, and whose level is at or above `floors["confirm-baseline"]`.

**Intent status** is the first of these that applies: `draft` if not confirmed; `uncovered` if a criterion has no obligation; `unguarded` if there are fewer hard gates than `min_hard_gates`; `open` if some hard criterion has an obligation that is not `passed`; `delivered` if some deferred criterion has one that is not `passed`; otherwise `fulfilled`.

Each intent also reports:

- `gates`: how many criteria are `hard`, `soft` and `deferred`, and `deferred_open`, how many deferred criteria have an obligation that is not `passed`.
- `score`: `met`, how many criteria have every obligation `passed`, `of` how many criteria.
- `separation`: there must be one act of kind `confirm-baseline` and one of kind `match-check` for each pairing of a criterion with an obligation that checks it. For each, take the highest level among the agreed act records for it in the ledger: for the confirmation, those that would confirm the intent but for the floor; for a pairing, those of kind `match-check` whose target is the identity of `{"intent": I, "criterion": C, "obligation": O}`. With no such record the level is `self`. `weakest` is the lowest of these levels; `act` is the kind it belongs to, `confirm-baseline` if both kinds have it; `apart_or_better` counts those at `apart` or above; `of` is how many there must be.

**Project status** is `nothing-required` if `required` is empty; otherwise `failed` if a hard criterion of a required intent has an obligation that is `failed` or `conflict`; otherwise `passed` if every required intent is `delivered` or `fulfilled`; otherwise `unknown`.

Exceptions, children and deferred time limits are left out of status scenarios; the intent and tree scenarios cover them.

## The ledger, and core keys

Two more things are judged, each by its own tool.

**Core keys.** `tools/run_key_vectors.py -- <kernel command>` starts the kernel with a preimage on standard input and requires `{"core_key": "<identity>"}`, or `{"refused": "<reason>"}` for the vectors that must be refused ([vectors](vectors/core-key.json)).

**The ledger file** ([format](../protocol/ledger.md)). `tools/run_ledger_cases.py -- <kernel command>` gives the kernel two subcommands. `ledger-append` takes `{"ledger": "<file>", "kind": K, "body": B, "wait_ms": N}` and answers `{"appended": "<identity>"}` or `{"refused": "locked" or "corrupt"}`. `ledger-read` takes `{"ledger": "<file>"}` and answers `{"entries": [...], "torn": true or false}` or `{"refused": "corrupt", "at": N}`. The judge appends entries through the kernel and requires the file to be, byte for byte, what the reference encoder produces; damages the file in each of the ways listed in `conformance/ledger/cases.json`, including a torn ending at every byte; has two kernels append at once and requires every entry to survive; and holds the lock itself and requires `locked`.

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
- The intent and attempts scenarios take a claim and its source as given. Working both out from an act record is in the acts and status scenarios.
- The levels above `helper` in the kit describe what a kernel must do when a harness vouches for an act. No harness that an agent cannot reach exists yet, so they are not reachable in practice today.
