# dodona data model

Status: **draft 0.3**, not implemented. This file defines the terms the [architecture](ARCHITECTURE.md) uses. Field-level schemas live in [protocol/](protocol/README.md).

## 1. Nodes

Every node has a **name** (stable, how it is referred to) and an **identity** (a content hash, how change is detected), except where noted.

| Node | Name | Identity | Comes from |
|---|---|---|---|
| Intent | Its id | Hash of the statement and criteria | The intent owner, through an intent provider |
| Amendment | Its id | Hash of the record | The intent owner |
| Definition | Path or symbol, scoped by the binding that indexed it | Hash of content, as the language provider defines content | `definition.index`, or the file-level fallback |
| Specification | A definition whose role is to state what must hold | Same as a definition | `definition.index` for the specification language |
| Decision | Its id | Hash of the record | `decision.index` |
| Obligation | Binding name plus a provider-chosen locator | Hash of binding and name. Stable across edits | `obligation.enumerate` |
| Artifact | Producing obligation plus output path | Hash of content | `artifact.build` |
| Tool | Name and version | Hash of the canonical tree listing | `tool.resolve` |
| Record | None | Hash of its canonical encoding | The kernel |
| Policy | None | Hash of the policy file | The project owner |

A specification is not a different kind of thing from a definition. Specifications are indexed, hashed and depended on like any other definition; the word names a role in an obligation.

## 2. Edges

| Edge | From → to | Meaning |
|---|---|---|
| `breaks-into` | Intent → intent | The child is part of delivering the parent |
| `checked-by` | Criterion of an intent → obligation, through a gate | The obligation is how the criterion is shown |
| `amends` | Amendment → intent | A recorded change to criteria or gates |
| `depends-on` | Definition → definition | Changing the target can change the meaning of the source |
| `governs` | Decision → definition name | The decision constrains this definition; records the identity at the time of writing |
| `supersedes` | Decision → decision | The older decision no longer applies |
| `specified-by` | Obligation → definitions | The specification side of an obligation |
| `targets` | Obligation → definitions or artifacts | What is being checked |
| `produced-by` | Artifact → obligation | The build that produced it |
| `requires` | Tool → tool | A tool that needs another to run |
| `evidences` | Record → obligation | A check that ran |

The **closure** of a definition is everything reachable from it over `depends-on`. An obligation's inputs are the closures of everything it is `specified-by` and `targets`, plus for each artifact the inputs of the obligation that produced it.

## 3. Obligations

An obligation is one question with a yes or no answer: *do these targets satisfy this specification, as judged by this provider with this configuration?*

Obligations are **enumerated by providers**, not invented by the kernel, because only the provider knows what its tool can do separately: one model with one configuration, one lemma, one test, one build target. Any provider offering `obligation.check`, `artifact.build` or `conformance.check` must also offer `obligation.enumerate`. The one exception is `reproducibility` obligations, which the kernel derives from policy and the records it holds. The kernel asks each binding for its obligations and receives, for each:

| Field | Meaning |
|---|---|
| `name` | Stable locator within the binding. Survives edits to the content |
| `specified_by`, `targets` | Definition or artifact names |
| `kind` | `check`, `build`, `conformance` or `reproducibility` |
| `expect` | `holds` or `violated` |
| `defect_of` | For a planted defect: the obligation whose check it must break |
| `config` | Bounds, flags, seeds, worker counts and limits |

**Planted defects are obligations.** An obligation with `expect: violated` passes when the checker finds the violation it names. Its `defect_of` field ties it to the obligation it guards. This is how dodona's own rule, that a check must be shown able to fail, becomes something the kernel tracks instead of a habit.

**Build is an obligation too.** `artifact.build` produces artifact nodes under an obligation of kind `build`. Anything that consumes the artifact depends on that obligation's inputs, so changing the compiler invalidates the tests of what it compiled.

## 4. Status

A **check** is one attempt to decide an obligation; it consists of one or more tool **runs** and ends in one of six verdicts, defined in [the architecture](ARCHITECTURE.md#5-verdicts-status-and-evidence). Status is what the kernel derives from the ledger.

**Ledger entries**

| Entry | Written | Holds |
|---|---|---|
| Submission | Once per check, before its first run is sent to an executor; updated with each run's handle as the executor accepts it | Obligation, core key, target platform, executor, handles |
| Evidence record | When a check ends `passed` or `failed` | Everything in the [record schema](protocol/evidence-record.schema.json) |
| Outcome | When a check ends `unavailable`, `error` or `unsupported` | The submission it closes, the verdict, a reason code, the log |

A submission with no closing entry is `pending`. Only evidence records are reusable. Outcome entries are what give `unknown` its reason.

**Status is per platform.** Policy names the platforms on which each obligation is required; the default is the platform of the executor bound to it. In the rules below, "the current key" means the core key computed now together with the platform being asked about. A record from a different platform counts only as a *stand-in*: when the provider claims platform independence, the same core key has been checked on at least two platforms with agreeing results, and policy accepts that. A status resting on a stand-in says so.

**Obligation status**

| Status | Rule |
|---|---|
| `passed` | At least one reusable record for the current key, all of them `passed` |
| `failed` | At least one reusable record for the current key, all of them `failed` |
| `conflict` | Reusable records for the current key disagree |
| `unknown` | No reusable record for the current key. Carries a reason: `never-run`, `pending`, `unavailable`, `error`, `unsupported` |

Each status also reports:

- `strength`: the provider's name for its kind of evidence (its evidence class, such as proof, bounded model check, test) together with a **rank** the provider picks from a list the kernel owns: `exhaustive` (all inputs), `bounded` (all inputs within stated bounds), `sampled` (some inputs), `documented` (no check, only a written mapping). Policy sets minimums by rank. A status reports the weakest rank among the records it rests on
- `non_vacuous`: `shown` if every planted defect of this obligation is itself `passed`, `not-shown` if any is not, `none-planted` if there are none
- `trusted_base`: the union of the kernel's, the provider's and the records' assumptions
- `isolation`: the weakest isolation level among the runs

A rerun never replaces a record. It adds one, and disagreement becomes `conflict`. A conflict is cleared only by a change of inputs or by an explicit, recorded decision to retire named records.

**Project status** is relative to the policy in force:

| Status | Rule |
|---|---|
| `passed` | Policy requires at least one obligation, and every required obligation is `passed` on every platform it is required on, at or above the required evidence class, non-vacuity and isolation |
| `failed` | At least one required obligation is `failed` or `conflict` |
| `unknown` | Otherwise, with the list of obligations that are not yet decided |
| `nothing-required` | Policy requires no obligation. Never shown as a pass |

The result also names the policy identity it was judged against, and whether that policy differs from the reference policy ([decision 0014](decisions/0014-policy-is-separate-from-configuration.md)).

## 5. Intent, gates and assurance

This is the layer that answers the question dodona exists for: *was what was defined actually built and delivered, and how sure is that?* ([0017](decisions/0017-intent-in-plain-words-broken-down.md) to [0020](decisions/0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md))

**Intent.** A statement in plain words, such as a problem, a feature or a story, with an owner and a list of criteria. It may break into child intents. Each intent declares what it expects to touch, so independent intents can be worked on in parallel and colliding ones are reported.

**Gate.** How a criterion is tied to the obligations that check it:

| Gate | Blocks delivery | When it is checked |
|---|---|---|
| Hard (default) | Yes | Before delivery |
| Soft | No; lowers stated assurance | Before delivery |
| Deferred | No; blocks *fulfilled* | After delivery, by a stated limit, typically on a live system |

A check on something that varies between runs declares the number of runs and how many must agree, and reports the measured rate with its sample size.

**Intent status**, always derived:

| Status | Rule |
|---|---|
| `uncovered` | At least one criterion has no obligation and no amendment |
| `open` | Covered; at least one hard gate is not passed |
| `delivered` | Every hard gate passed. Reports the open deferred gates |
| `fulfilled` | Delivered, and every deferred gate closed |
| `overdue` | Delivered, and a deferred gate passed its limit while open |

A parent needs its children delivered and its own criteria met.

**Assurance.** Each criterion reports a level for each link from intent to running system, on one scale:

`proven` > `bounded` > `sampled` > `observed` > `asserted` > `none`

| Link | Typical source of the level |
|---|---|
| Intent → definition | Owner confirmed the criteria: `asserted` by the owner. Unconfirmed: `none` |
| Definition → specification | Share of the criterion covered by formal statements |
| Specification → code | The rank of the conformance evidence |
| Code → what runs | Whether the delivered artifact is the one that was checked, by identity |
| What runs → the world | Deferred gates: `observed`, with how many observations |

The criterion's assurance is its **weakest link**. The intent's score is a count: criteria at or above the level their gate demands, out of all criteria. Every report shows the count, the weakest link, and where it is.

**Amendment.** Any change to criteria or gates after work started. Granted only by the intent owner, recorded with what changed, why and by whom, never erased. An amended criterion is at most `asserted` for the part amended. An amendment granted by the party that did the work is **self-granted**: shown first in every report, and not counted at all where policy requires an independent approver, which is the recommended setting.

## 6. Trusted base

One list, referred to from everywhere else. Every status reports the subset it rests on.

Assumed by the kernel's design:

1. A provider's verdict is correct for the inputs it was given.
2. A provider declares every input its result depends on.
3. Equal identities mean equal content.
4. The input copy handed to a run is not altered while the run uses it.
5. The executor ran the tools it reported, on the platform it reported.
6. The ledger keeps what was written and does not alter it.
7. The kernel itself, and the seed it was built from, behave as specified.
8. Each pinned tool is what its upstream published.
9. The specification states the property that was actually intended.
10. Whoever can change policy is authorised to.
11. An intent's owner is who the record says, and an owner confirming criteria has read them.

Declared by each provider in its manifest, for example: the model checker is correct, the language runtime under it is correct, the foreign-function shell is not covered by the proof.

Reported per record, for example: this proof used these axioms; this run was not isolated.

Assumptions 1, 2 and 5 are not left as pure trust. The conformance kit perturbs a provider's environment to look for undeclared inputs, the executor's report is compared with the lock, and a second platform or a second run can expose a wrong verdict as a conflict. None of that removes the assumption; it makes violations more likely to be seen.

## 7. Agent interface

A sketch, to be replaced by schemas. Every command takes and returns structured data, never prompts, and can be run repeatedly with the same result. A command never waits for a long check; it returns and can be asked again.

| Command | Does | Returns |
|---|---|---|
| `resolve` | Reads configuration, produces or verifies the lock | Lock identity, anything unresolvable per platform |
| `index` | Asks providers for definitions, decisions and obligations | Graph summary and every rejected path or file with a reason code |
| `status` | Derives status from the graph and ledger | Project status; per intent: status, score, weakest link, amendments, self-granted first; per obligation: status, reason, strength, non-vacuity |
| `plan` | Works out what is stale | Ordered obligations to run, each with why it is stale |
| `run` | Submits planned obligations to executors | Run handles; verdicts for anything that finished |
| `explain` | Traces one result | Its key structure, records, trusted base, and the decisions governing its targets |
| `review` | Lists decisions whose governed definitions changed | Decision, name, old and new identity |
| `reproduce` | Compares records with one core key across platforms | Agreement, disagreement or `unknown` per obligation |

Errors carry a stable code, the node concerned, and no information that exists only as prose.
