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
| `ledger/cases.json` | The exact bytes of a ledger, and ways of damaging it |
| `ledger/more-damage.json` | More damaged ledgers, each as a whole file with what a reader must answer, and requests to append that must be refused |
| `vectors/core-key.json`, `vectors/core-key-more.json` | The key of an evidence record from the inputs it states, and inputs that must be refused |
| `kernel/index.json` | The modelled cases that have no scenario, each with the reason |
| `provider/misbehaving_provider.py` | A provider that does one thing wrong in each of its modes: garbage, a byte-order mark, a carriage return, bad encoding, an over-long line, half a line, no answer, a late answer, a wrong or repeated answer, a flood on standard error, a process left behind |
| `provider/cases.json` | What a host must do with it in each mode |
| `vectors/canonical.json` | The [canonical encoding](../protocol/canonical-encoding.md): values with their exact text and hash, and inputs that must be refused |
| `vectors/paths.json` | The [path check](../protocol/path-check.md): accepted paths, refused paths with the reason, and sets that collide |

Every scenario names the claim it bears on and the model cases it covers. Each planted defect in the formal models has at least one scenario that a kernel repeating that defect fails. The repository checks enforce this.

## How a kernel is judged

`tools/run_kit.py -- <kernel command>` starts the kernel once per scenario, with the scenario as JSON on standard input. The kernel is shown what happens in each step and nothing else: the expected results and the notes about the scenario are removed first. The kernel prints `{"results": [...]}` with one result per step. Every step shown in the tables below is valid at any point of a scenario, in any order and any number of times; where a step has nothing to act on, the section says what happens. In every kind, a step that names something the scenario does not have (a criterion, an obligation, a definition, a run, a child, a ticket, a platform, a key, an intent) changes nothing, and a step whose value is not one the tables allow (a gate, a verdict or a level that does not exist) changes nothing either. A step that carries a value of another type than the tables give (a name that is not a string, a verdict that is a number, a list where a word belongs) changes nothing either, in every kind, as if the value were one the tables do not allow. A kernel answers every step; it never stops on one.

A kernel reads every input as strictly as the [canonical encoding](../protocol/canonical-encoding.md) writes: a key repeated in one object, or a number that is not written as an integer (`1.0`, `1e0`, `10E-1`), makes the whole input refused, and the kernel exits with a status other than 0. Otherwise a record could be signed with one value and read with another. `tools/run_input_cases.py` judges this. A scenario matches when every field its steps expect is present and equal. A crash, a timeout or anything else is a mismatch.

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
- `reason` is `pending` if a run on the current inputs is in flight; otherwise the outcome of the most recent attempt on the current inputs that left no result, `unavailable` or `error`, where attempts are ordered by when they were asked for (their `submit`), not by when they ended; otherwise `never-run`. A lost run gives `error`.
- Recorded results take precedence over a run in flight: an obligation that has passed stays `passed` while it is being checked again.
- A run is in flight from the `submit` that started it until it is completed or lost. A `complete` or `lose` naming a run that is not in flight changes nothing. A `submit` under a name that is in flight changes nothing, whatever the backend and whichever obligation it asks for: names are shared by all obligations, and no `unavailable` is recorded. Once a run has ended, by a `complete` or a `lose`, its name may be used again.

### Intent scenarios

A scenario gives the criteria with their gates as first written, and a policy: `exception_separation`, the least separation at which an exception takes effect, and `min_hard_gates`.

| Step | Meaning |
|---|---|
| `{"confirm": {}}` | The owner confirms the gates as they stand |
| `{"check": {"criterion": C, "status": S}}` | The check behind C now has status S: `unknown`, `passed`, `failed` or `conflict` |
| `{"edit": {"criterion": C, "to": G}}` | The gate of C is changed directly, not by an exception |
| `{"amend": {"criterion": C, "to": G, "by": "owner" or "worker", "claims": L, "source": "declared" or "attested"}}` | An exception is asked for. `claims` is the separation level the record claims and may be absent. `source` says who stands behind the claim and is `declared` when absent |

The result after each step has `"status"`, and after an `amend` step also `"amendment": {"takes_effect": true or false, "level": L}`. Every `amend` step gets that answer. One that names a criterion that does not exist, or whose `to`, `by`, `claims` or `source` is not a value the table allows, does not take effect, changes nothing, and has the level `self`.

- `level` is the separation the kernel grants. It is `self` if the worker is the grantor or nothing is claimed. Otherwise it is the claimed level, capped by its source: a `declared` claim earns `helper` at most, an `attested` one `cross-make` at most.
- An exception takes effect only if the owner granted it and its level is at or above the policy floor. The levels in order are `self`, `helper`, `apart`, `tested`, `cross-make`, `credentialed`. An exception that takes effect is the owner's own act and leaves the intent confirmed.
- A soft gate never affects the status, whatever its check says.
- `min_hard_gates` is at least 1. A lower value is treated as 1.
- An `edit` that sets a gate to what it already is changes nothing.
- An `amend` that names a criterion the intent does not have changes nothing: the amendment does not take effect and its level is `self`, whoever asks and whatever it claims.
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

A scenario gives a `root` and `children`, each with the gate of its one criterion, `hard` or `soft`, and a policy with `min_hard_gates`. There may be no children. Adding a child that is already there, setting a gate to what it already is, a gate other than `hard` or `soft` in an `edit` or an `add`, or a step that names a child that is not there, changes nothing.

| Step | Meaning |
|---|---|
| `{"confirm": {}}` | The owner confirms the tree as it stands |
| `{"check": {"node": N, "status": S}}` | The check behind N's criterion now has status S, one of `unknown`, `passed`, `failed` or `conflict`. N is `root` or a child |
| `{"edit": {"node": N, "to": G}}` | N's gate is changed directly |
| `{"remove": {"child": K}}` | Child K is removed |
| `{"add": {"child": K, "gate": G}}` | Child K is added, its check unknown |

The result has `"status"`, the first of these that applies: `draft` if the owner has not confirmed, or anything was edited, added or removed since; `unguarded` if the tree counts fewer hard gates than `min_hard_gates`, or fewer than one, counting the root and every child; or if any child has no hard gate (decision 0030). A child is not held to the policy's number on its own: moving a criterion into a child loses nothing (decision 0017). `open` if any hard gate's check is not `passed`; otherwise `delivered`.

### Attempts scenarios

| Step | Meaning |
|---|---|
| `{"take": {"as": T}}` | A ticket T is taken for an attempt at judging the current target. The attempt is open |
| `{"close": {"ticket": T, "result": "agreed" or "refused"}}` | The attempt is closed with that result |
| `{"change_target": {}}` | The thing being judged changes |

A scenario may give `claims`, the separation level the act claims, and `refusals_before_cap`, a whole number of at least one, 2 when absent. Any other value of `refusals_before_cap` (zero, a negative number, a fraction, a string) makes the scenario invalid, and the kernel refuses it as it refuses any invalid input: a non-zero exit and no result. Closing a ticket that was never taken, or is already closed, changes nothing. A ticket taken before a change of target can still be closed.

The result has these fields. Every field is worked out from the attempts as they stand now, in the order they were taken; the first two from those on the current target only. So closing an earlier open attempt as agreed can clear `retried`.

- `"result"`: `none` if there are none; `agreed` if every one is closed as agreed; otherwise `refused`. An open attempt counts as a failure.
- `"shopped"`: true if some attempt closed as agreed was taken after one that is not agreed.
- `"cap"`: `helper` when shopped, or when retried and the line has at least `refusals_before_cap` attempts that are not agreed, otherwise null (decision 0031). A change of target does not reset the count, and an agreement after a change keeps its grade only until that limit: the kernel cannot tell a real fix from a trivial change.
- `"attempts"`: how many tickets have been taken in all, across changes of target.
- `"retried"`: true if, among all attempts across changes of target, some attempt closed as agreed was taken after one that is not agreed.
- `"granted"`, when the scenario gives `claims`: the claimed level, lowered to `helper` if `cap` is `helper` and the claim was higher. The cap never raises a level.

### Platforms scenarios

A scenario gives `keys` (sets of inputs), any number of `platforms`, whether policy allows a record from one platform to stand in for another, `stand_in_allowed`, and whether the provider claims its results do not depend on the platform, `provider_claims`, true when absent. Each step is `{"record": {"key": K, "platform": P, "verdict": "passed" or "failed"}}`. A second record for the same key and platform with the same verdict changes nothing; with the other verdict it makes that platform's own status `conflict`.

- `"status"`, by key then platform: the platform's own verdict if it has one, or `conflict`; otherwise another platform's verdict for the same key, if standing in is allowed, the provider claims platform independence, and the claim is verified; otherwise `unknown`. The claim is verified for a key when that key has the same verdict on at least two platforms, whether passed or failed, and no platform, the one asked about included, has recorded the other verdict for that key. Another key agreeing verifies nothing about this one. When a stand-in is allowed all of the key's verdicts are the same, so it does not matter which platform's is taken.
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

How separate was the party behind an act of judgement ([decision 0024](../decisions/0024-separation-is-graded-not-enforced.md)). A scenario gives a `policy` with `attestors`, a map from key name to a key in hexadecimal, and `makes`, a list of groups of `vendor/family` names that count as the same make. A group that is not a list of strings is ignored, and a name matches only a name equal to it, never part of one. Each step is `{"grade": R}` where R is an act record ([schema](../protocol/act-record.schema.json)). The keys in the kit are fixtures, public by design.

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

A fact is **vouched for** when every field it reads is listed in `attestation.covers`, `attestation.key` names a key in `attestors`, and `attestation.mac` is the HMAC-SHA256, under that key, of the canonical encoding of `{"covers": C, "fields": F}`, where C is `covers` and F holds each covered field of the record under its name. A record with no attestation, a key the policy does not name, or a mac that does not match, has no fact vouched for. A covered field that the record does not have is left out of F. The fact distinct needs vouching like any other: without it nothing above `helper` is granted.

The check value is exact:

- `mac` is 64 lowercase hexadecimal digits and is compared in full. The same value in uppercase, or one that matches only in part, vouches for nothing.
- `covers` is used in the order the record gives it. It must already be sorted as the canonical encoding sorts keys, with no name repeated. A list in any other order, or with a repeat, vouches for nothing, even if the mac was made over that very list.
- A key in `attestors` is a non-empty string of lowercase hexadecimal digits, of even length. Anything else (an empty string, an odd number of digits, an uppercase digit, a character that is not a digit) names no key: nothing is vouched for under it. The attestation's `harness` must be the same as its `key`: a value that names one harness and was made with another's key vouches for nothing. An attestation with no `harness` vouches for nothing either.

**A check value binds the whole record.** No level above `helper` is granted unless `covers` lists every field the record has at the top level, other than `attestation` itself, and lists at least `ticket`, `kind`, `target`, `result` and `lineage`. So nothing can be added to a signed record, or changed in it, without breaking the mac: not what was judged, not the ticket, and not a field nobody reads today. An attestation with a field other than `harness`, `key`, `covers` and `mac` vouches for nothing. A record that does not meet this keeps its `claims` and is graded `helper`, `declared`.

**A malformed record is `self`.** Its `claims` is `self`, its `level` is `self` and its `source` is `declared`, whatever it says and whoever signed it. A record is malformed when any of these is true, and in no other case:

- It has a field at the top level that the act record does not define: anything other than `ticket`, `kind`, `target`, `result`, `lineage`, `actor`, `worker`, `brief`, `given`, `fresh_context`, `known_bad`, `attempt`, `transcript` and `attestation`. A field nobody signs cannot ride along on a signed record.

- `actor` or `worker` is missing or is not an object, or the `id` or the `session` of either is not a string. A missing `id` or `session` is not a string.
- A field that is present has the wrong type:
  - `brief` is not an object;
  - `given` is not a list of objects, each with a string `role` and a string `content`;
  - `fresh_context` is not a boolean;
  - `transcript` is not a string;
  - `known_bad` is not an object, or lacks a string `wrong`, `right` or `supplied_by`, or a boolean `rejected_wrong` or `accepted_right`;
  - `attestation` is not an object with a string `key`, a string `mac` and a list of strings `covers`;
  - `kind`, `target` or `result` is not a string;
  - `lineage` is not an object;
  - `ticket` is not a string;
  - `actor.started_by` is present and is not a string;
  - `attempt` is not an object with an integer `number` and an integer `prior`.

A field that is simply absent does not make a record malformed, except that `actor` and `worker` must be there. A value of the right type that no table allows, such as a role of `other`, is not malformed either.

`level` is the highest level, not above `claims`, that is `self` or `helper`, or all of whose facts and the facts of the levels below it are vouched for by a check value that also binds what was judged. `credentialed` is never granted.

### Status scenarios

What a kernel reports about a whole project. A scenario gives:

- `self`: this kernel's `writer` name and its `platform`.
- `policy`: `min_hard_gates`; `required`, the intents that must be delivered; `trusted_writers`; `floors`, the least separation at which an act of each kind counts; and `attestors` and `makes` as in acts scenarios.
- `obligations`: for each name, the `preimage` of its core key as things stand ([vectors](vectors/core-key.json)).
- `intents`: for each id, its `owner`, its `worker`, its `children`, optionally `words`, the intent as written, and its `criteria`, each with a `gate`, `checked_by`, a list of obligation names, and optionally `words`, the criterion as written.

| Step | Meaning |
|---|---|
| `{"append": {"kind": "evidence", "body": B}}` | A record is added to the ledger. B has `obligation`, `preimage`, `core_key`, `platform`, `verdict` and `writer` |
| `{"append": {"kind": "act", "body": R}}` | An act record is added to the ledger |
| `{"change": {"obligation": O, "preimage": P}}` | The inputs of O are now P |
| `{"set_gate": {"intent": I, "criterion": C, "to": G}}` | A gate is edited directly |

The result has `obligations` and `intents`, each an object with one entry per name; `project`, an object with a `status`; and `rejected`, a number. A floor that policy does not give is `self`.

**Obligations.** An evidence record is *not a record* if its body is not an object, if its `verdict` is not `passed` or `failed`, or if it lacks `obligation`, `platform`, `writer`, `core_key` or `preimage`. A field of the wrong type counts as lacking: `obligation`, `platform`, `writer` and `core_key` must be strings and `preimage` an object. Such an entry does not count for anything and is not counted as rejected either. Any other evidence record is *rejected* if its `core_key` is not the identity of its own `preimage`, or its preimage is one the core-key rules say must be refused; `rejected` is how many such records the ledger holds. A record that is not rejected *counts* for the obligation it names, and for no other, when its writer is this kernel or one of `trusted_writers`, its platform is this kernel's, and its `core_key` is the identity of the obligation's preimage as things stand. An obligation is `passed` if records count and all are passed, `failed` if all are failed, `conflict` if they differ, and otherwise `unknown` with `"reason": "never-run"`. An obligation named in a `checked_by` that the scenario does not define is `unknown`, `never-run`: the criterion has an obligation, and it has not passed.

**A gate nobody can read is hard.** A criterion whose `gate` is not exactly `hard`, `soft` or `deferred` (`Hard`, a gate with a hidden character, anything else) counts as `hard` in every rule: in the floor, in `open`, in `gates`. A mistake in writing a gate can only make delivery harder, never easier. The baseline keeps the gate as written.

**Baseline.** Lists marked sorted are sorted as the canonical encoding sorts keys. The baseline of an intent is the identity of `{"owner": O, "words": T, "children": [sorted], "criteria": {C: {"words": W, "gate": G, "checked_by": [sorted]}}}`, where T is the intent as written, all of it, and W is each criterion's wording, each the empty string when the scenario gives none. Changing anything in what the owner confirmed, a title, a row, a hidden comment, changes the baseline. Rewording a criterion changes the baseline, so a confirmation of the old words stops counting.

**Acts.** An act record is graded as in acts scenarios, a malformed one as `self`, with one more rule: if its `worker.id` is not the intent's `worker`, its level is `self`. An act entry whose body is not an object takes part in no rule. An intent is *confirmed* when the ledger holds an act of kind `confirm-baseline` whose `lineage.intent` is the intent, whose `result` is `agreed`, whose `target` is the intent's baseline as things stand, whose `actor.id` is the intent's owner, and whose level is at or above `floors["confirm-baseline"]`.

**Intent status** is the first of these that applies: `draft` if not confirmed; `uncovered` if a criterion has no obligation; `unguarded` if there are fewer hard gates than `min_hard_gates`; `open` if some hard criterion has an obligation that is not `passed`; `delivered` if some deferred criterion has one that is not `passed`; otherwise `fulfilled`.

Each intent also reports:

- `baseline`: the baseline of the intent as things stand, the identity defined above. It is what a confirmation must name.
- `gates`: how many criteria are `hard`, `soft` and `deferred`, and `deferred_open`, how many deferred criteria are not met.
- `score`: `met`, how many criteria are met, `of` how many criteria. A criterion is met when it has at least one obligation and every one is `passed`. A criterion that nothing checks is never met.
- `shown`: `level` and `criterion`. An evidence record may state a `level`, one of the scale in the assurance scenarios; one that states no level, or something not on the scale, is `asserted`. A record that states the level `none` is taken at `none`: it is on the scale. An obligation that is `passed` has the strongest level among the records that count for it; any other obligation has `none`. A criterion has the weakest level among its obligations, and `none` if it has no obligation. `level` is the weakest among all the intent's criteria, soft ones included, and `criterion` is the first criterion at that level, in the order in which the canonical encoding sorts keys. An intent with no criteria shows `"level": "none"` and `"criterion": null`.
- `exceptions`: `counted` and `below_floor`. Among the agreed act records of kind `grant-amendment` whose `lineage.intent` is the intent: one counts if its `actor.id` is the intent's owner and its level is at or above `floors["grant-amendment"]`; every other is below the floor. A refused one is neither. In status scenarios an exception changes no gate; the intent scenarios judge what it changes.
- `separation`: there must be one act of kind `confirm-baseline` and one of kind `match-check` for each pairing of a criterion with an obligation that checks it. For each, take the highest level among the agreed act records for it in the ledger: for the confirmation, those that would confirm the intent but for the floor; for a pairing, those of kind `match-check` whose target is the identity of `{"intent": I, "criterion": C, "obligation": O}`. A match-check is found by its target alone. Its `lineage` is not read: one whose lineage names another criterion, or another intent, still counts for the pairing its target names, and for no other. With no such record the level is `self`. `weakest` is the lowest of these levels; `act` is the kind it belongs to, `confirm-baseline` if both kinds have it; `apart_or_better` counts those at `apart` or above; `of` is how many there must be.

**Project status** is `nothing-required` if `required` is empty; otherwise `failed` if a hard criterion of a required intent has an obligation that is `failed` or `conflict`; otherwise `passed` if every required intent is `delivered` or `fulfilled`; otherwise `unknown`. A required intent that the scenario does not define counts as not delivered, so the project cannot be `passed`.

A ledger may hold entries of other kinds, and an evidence body may carry more fields than those named. A kernel ignores both: they take part in no rule.

A step that names an obligation, intent or criterion that does not exist changes nothing. A kernel answers every step and never stops on one: not on a body that is empty or is not an object, not on an act with no actor, not on a name nothing defines. The floor for `match-check` is read by no rule yet: a pairing's level is reported, and nothing is withheld for it.

What an exception changes, children and deferred time limits are left out of status scenarios; the intent and tree scenarios cover them.

## The ledger, and core keys

Two more things are judged, each by its own tool.

**Core keys.** `tools/run_key_vectors.py -- <kernel command>` starts the kernel with a preimage on standard input and requires `{"core_key": "<identity>"}`, or `{"refused": "<reason>"}` for the vectors that must be refused ([vectors](vectors/core-key.json), [more vectors](vectors/core-key-more.json)).

- Every set in a preimage (`specified_by`, `targets`, `closure`, `declared`, `mapping`) must arrive sorted as the canonical encoding sorts keys, that is by UTF-16 code units, with no member repeated. Every set is checked, not only `closure`. Two members in descending order are unsorted. A repeat in any set is refused. The reason is `unsorted-set` in each case.
- A field the preimage definition does not have is refused. For `platform`, at the top level or inside `inputs`, and whatever its value, null included, the reason is `platform-in-core-key`. Any other field at the top level that the definition does not have is refused with the reason `unknown-field`.

**The ledger file** ([format](../protocol/ledger.md)). `tools/run_ledger_cases.py -- <kernel command>` gives the kernel two subcommands. `ledger-append` takes `{"ledger": "<file>", "kind": K, "body": B, "wait_ms": N}` and answers `{"appended": "<identity>"}` or `{"refused": "locked", "corrupt" or "bad-request"}`. `ledger-read` takes `{"ledger": "<file>"}` and answers `{"entries": [...], "torn": true or false}` or `{"refused": "corrupt", "at": N}`. The judge appends entries through the kernel and requires the file to be, byte for byte, what the reference encoder produces; damages the file in each of the ways listed in `conformance/ledger/cases.json`, including a torn ending at every byte; reads each whole file in `conformance/ledger/more-damage.json`; has two kernels append at once and requires every entry to survive; and holds the lock itself and requires `locked`.

- `kind` is any non-empty string. A reader keeps entries of every kind, and an append after an entry of a kind it gives no meaning works as after any other.
- A line is exactly `dodona1`, one space, the length in decimal with no sign and no leading zero, one space, 64 lowercase hexadecimal digits, one space, the payload, and a line feed. Anything else is corrupt at that line: two spaces, a tab, a byte-order mark, an empty line, bytes after the payload, an uppercase digit, another first word.
- The length and the checksum are both compared with the payload. `previous` must be exactly the identity of the entry before, and null in the first entry only. A payload that is not an object with exactly `previous`, `kind` and `body` is corrupt.
- An append to a corrupt ledger answers `{"refused": "corrupt"}` and leaves the file as it was.
- A `ledger-append` with no string `kind`, or with no `body`, answers `{"refused": "bad-request"}` and writes nothing: no entry, no file, no lock left behind.

## How a host is judged

`tools/run_provider_cases.py -- <host command>` starts the host once per case and has it run the misbehaving provider in that mode. A case matches when the host reports the expected outcome and reason, returns within the deadline plus a grace period, and nothing the provider started is still running. The first case is a well-behaved provider that must be accepted: a host that refuses everything would otherwise pass.

`tools/provider_host.py` is a small reference host, there to show the session rules can be kept on macOS, Linux and Windows. It checks framing, encoding, line length, deadlines and message envelopes, and ends every process the provider started. It does not validate message bodies against the schemas, and it is not part of any kernel yet.

### Rules a schema cannot express

`tools/run_check_cases.py` judges `tools/host.py`, the stage-0 program that takes a check from a provider to a verdict ([decision 0026](../decisions/0026-the-first-host-and-status-are-stage-0-helpers.md)). `provider/misbehaving_checker.py` sends only well-formed messages and breaks one rule in each mode: a verdict with no run behind it, more strength than its manifest declares, a tool it never declared, a path that leaves its tool or its working directory, an input that is not in the key. `provider/check-cases.json` lists what the host must do. Nothing may be recorded as passed except in the controls, and where a run would have been dangerous it must not have started.

The rules the host keeps, each with a case that fails when the rule is taken out:

- A run starts only tools the manifest declares **and** the check was given. A declared tool the check was not given is not in the key of the result: `tool-not-in-key`.
- Every `${tool:NAME}` in an argument names a tool, with or without a file after it, and every one in an argument is looked at.
- The `tools` a run description lists are among those the check was given, with the same digests: `tool-digest-mismatch` otherwise.
- A verdict states the `class` of strength the manifest declares as well as a rank no higher: `strength-class-mismatch` otherwise. The ceiling and the need for a run hold for `failed` as for `passed`.
- A check may ask for at most 8 runs. The request for a ninth is refused with `too-many-runs` before it starts.
- An answer carries the id of its request, an argument holds no NUL, and the opening echo comes back unchanged.

This judges that one host. No kernel hosts a provider yet.

## Two kernels compared

`tools/kernel_differential.py --a <kernel> --b <kernel>` replays every scenario with its steps drawn again at random, repeated, dropped and reordered, and requires the two kernels to give the same answer in full, not only in the fields a scenario names. A difference, or an input neither answers, becomes a scenario. Agreement is not correctness: two kernels can be wrong the same way.

`tools/run_attest_check.py -- <kernel> scenario` has a kernel grade act records whose check values are made at test time by the reference signer, `tools/attest.py`, and requires it to stop accepting them once the record is changed.

`tools/run_harness_check.py -- <kernel> scenario` runs the reference harness, `tools/harness.py`, which really starts a checker in a directory holding only what it was given. With `harness/checker_reads.py`, which reads its files, the kernel must grade the signed record `cross-make`, `tested` or `apart` according to what the harness was given. With `harness/checker_nods.py`, which agrees with everything, the known-wrong case exposes it and the grade stops at `apart`. A record changed after signing, signed with a key policy does not list, or written without the harness, stays at `helper`.

## Rules for the kit

- A scenario is added before the behaviour it tests, and is committed before any kernel that will be judged by it.
- Expected results are written by hand from the documents and the models, never produced by a kernel.
- Two kernels that both pass the whole kit and still disagree on some input mean the kit is missing a scenario; the disagreement becomes one.
- Hostile names and bytes are stored as escaped data inside the vectors, never as real files, so the kit can be checked out on every platform.

## Not yet in the kit

- The evidence entries and the status report in the kit are smaller than `protocol/evidence-record.schema.json` and `protocol/status.schema.json` describe. Those schemas are the target, and nothing validates a kernel's output against them yet.
- A kernel that hosts providers. The rules for provider messages are judged on two stage-0 hosts only.
- Kit adequacy: running kernels with known defects against the kit and reporting the fraction it rejects.
- Anything not modelled: the ledger's crash behaviour, time limits, varying checks, executors, the lock, more than one level of child intents.
- The intent and attempts scenarios take a claim and its source as given. Working both out from an act record is in the acts and status scenarios.
- Rules that are written above and have no scenario yet: `min_hard_gates` below 1 in a tree, which is treated as 1 as everywhere else; a floor missing from policy. Both kernels were written from the same sentences, and nothing checks they read them the same way.
- What happens when a ticket name is taken a second time. The contract does not say.
- Rules written above with no scenario or vector yet: a set in a core-key preimage whose order differs between UTF-8 bytes and UTF-16 code units (the members are identities, which are ASCII, so no valid preimage can show it); an unknown field inside `inputs` other than `platform`; a ledger entry or an append whose `kind` is the empty string; an append whose `body` is null; an evidence field of the wrong type; an act whose `started_by` or `make` has the wrong type.
- The status scenarios added after the second review still use few shapes: no scenario has children that are themselves intents in the scenario, and only one has a floor above `helper`.
- The levels above `helper` in the kit describe what a kernel must do when a harness vouches for an act. No harness that an agent cannot reach exists yet, so they are not reachable in practice today.
