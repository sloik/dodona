# dodona data model

Status: **draft 0.4**, not implemented. This file defines the terms the [architecture](ARCHITECTURE.md) uses. Field-level schemas live in [protocol/](protocol/README.md).

## 1. Nodes

Every node has a **name** (stable, how it is referred to) and an **identity** (a content hash, how change is detected), except where noted.

| Node | Name | Identity | Comes from |
|---|---|---|---|
| Intent | Its id | Hash of its baseline: statement, criteria, gates, limits, links to checks and children. Worked out by the kernel | The intent owner, through an intent provider |
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

- `strength`: the provider's name for its kind of evidence (its evidence class, such as proof, bounded model check, test) together with a **rank** the provider picks from a list the kernel owns: `exhaustive` (all inputs), `bounded` (all inputs within stated bounds), `sampled` (some inputs), `documented` (no check, only a written mapping). Policy sets minimums by rank. A rank maps onto the evidence scale as: exhaustive, `proven`; bounded, `bounded`; sampled, `sampled`; documented, `asserted`. The rank in a provider's manifest is a ceiling, and a result claiming more is lowered to it. A status reports the weakest rank among the records it rests on
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

**Intent.** A statement in plain words, such as a problem, a feature or a story, with an owner and a list of criteria. It may break into child intents. Each intent declares what it expects to touch, so independent intents can be worked on in parallel and colliding ones are reported. A check that touches something its intent did not declare is reported as an undeclared touch.

**Baseline.** An intent's identity covers everything that sets the bar: its statement, criteria, the gate of each criterion, time limits, sample sizes and thresholds, the links from criteria to checks, and its set of children. A time limit is a length of time counted from delivery, not a date, so no clock takes part in the identity; the due date shown in a report is worked out from the recorded delivery. The owner **confirms** an intent by a record that names that identity and the confirmer. The confirmed identity is the baseline. Any later difference from it, in any of those parts, is an amendment, and voids the confirmation until the owner confirms again. An intent that has never been confirmed is a `draft` and can never be delivered.

**Gate.** How a criterion is tied to the obligations that check it:

| Gate | Blocks delivery | When it is checked |
|---|---|---|
| Hard (default) | Yes | Before delivery |
| Soft | No; lowers stated assurance | Before delivery |
| Deferred | No; blocks *fulfilled* | After delivery, by a stated limit, typically on a live system |

Policy sets the floor that an owner's choices cannot go below without it showing: the minimum number or share of hard gates, the longest limit a deferred gate may have, the minimum number of runs and agreement for a check on something that varies, and the least separation at which each kind of act takes effect. A deferred gate is closed by an observation, graded for separation like any other act.

**Intent status**, always derived:

| Status | Rule |
|---|---|
| `draft` | Not confirmed by its owner, or changed since it was |
| `uncovered` | At least one criterion has no obligation |
| `unguarded` | No hard gate anywhere in the intent or its descendants, or fewer than policy demands. Never becomes delivered |
| `open` | Covered and guarded; at least one hard gate is not passed, or a hard criterion is below the level policy demands |
| `delivered` | Every hard gate passed at the demanded level. Reports the open deferred gates |
| `fulfilled` | Delivered, and every deferred gate closed |
| `overdue` | Delivered, and a deferred gate passed its limit while open |

A parent needs its children delivered and its own criteria met. Gate counts and scores are totalled over all descendants, so moving a criterion into a child changes nothing in the total.

**The status word is never reported alone.** Every result for an intent leads with the same line, in this order:

```
delivered · gates: 4 hard, 1 soft, 1 deferred (open, due 2027-01-31)
          · shown: bounded (weakest evidence link: specification → code)
          · agreed: criteria confirmed by <who>; checks matched to criteria by <who>
          · separation: helper (claims apart), 0 of 6 acts apart or better; weakest: grant-amendment
          · attempts: 1
          · exceptions: 1
```

**Two kinds of link.** Between plain words and a running system there are links of two different kinds, and dodona never mixes them into one figure.

*Judgement links* can only ever be someone's word. dodona records whose word, and grades how separate that party was from the work.

| Link | Whose word |
|---|---|
| Intent → criteria: do the criteria say what was meant? | The owner, by confirming the baseline |
| Criterion → check: does this check really test this criterion? | A named reviewer |

dodona cannot judge either of these, and says so. What it can do is make sure the answer is on record, tied to an exact identity, with its separation graded.

*Evidence links* have a level from one scale, strongest first:

`proven` > `bounded` > `sampled` > `observed` > `asserted` > `none`

| Link | Source of the level |
|---|---|
| Specification → code | The rank of the checking or conformance evidence |
| Code → what runs | Whether the delivered artifact is, by identity, the one that was checked |
| What runs → the world | Deferred gates: `observed`, with how many observations and by whom |

Every evidence link is always evaluated. One with nothing reported is `none`; a link can be declared not applicable only in the baseline, where the owner confirmed it. A result measured over several runs is `sampled` with its count, so one run is `sampled (1 of 1)` and reads as what it is.

A criterion's **shown** level is its weakest evidence link. An intent's score is a count: criteria whose shown level is at or above what policy demands for their gate, out of all criteria.

**Separation.** How separate the party behind an act was from the work ([0024](decisions/0024-separation-is-graded-not-enforced.md)). dodona cannot enforce independence, so it grades it:

`self` < `helper` < `apart` < `tested` < `cross-make` < `credentialed`

| Level | In one line |
|---|---|
| `self` | The worker did it, or nothing is recorded. The default |
| `helper` | Someone else, but started, briefed or informed by the worker |
| `apart` | A fresh session that saw only the thing to judge and the criteria, briefed by someone other than the worker |
| `tested` | `apart`, and given a known-wrong and a known-right case unlabelled, it rejected the one and accepted the other |
| `cross-make` | `tested`, and a different make from the worker by policy's list of makes. A script is not a make |
| `credentialed` | `cross-make`, signed with a credential the worker cannot create. Not available yet |

**A claim is not a grade.** The grade is the level the record supports, capped by who stands behind its facts: facts that are only `declared`, including by the party that did the work, earn `helper` at most; facts `attested` by a harness whose key is listed in protected policy earn up to `cross-make`; the top level needs a credential the worker cannot create. A capped grade is shown with its claim, as `helper (claims apart)`. The kernel works out the source of each fact; a record cannot say how well supported it is. **Nothing can attest yet, so today the highest grade is `helper`.**

The worker is the whole party in control of the work: an orchestrating agent, the sub-agents it starts and any role it gives itself.

Separation is graded for the acts that rest on someone's word:

| Act | Below policy's floor |
|---|---|
| Confirming an intent's criteria and gates | The intent stays a `draft` |
| Saying that a check tests a criterion | The criterion is capped at `asserted` |
| Granting an amendment | The amendment is recorded and does not take effect |
| Closing a deferred gate by observation | The gate stays open |
| Changing policy | The change does not take effect |

The result of a check anyone can run again from locked inputs is graded on the evidence scale, not here; saying that it tests the criterion is still an act, and is graded. Separation is a separate axis: it is never multiplied into the evidence level. The kernel works out which acts there must be, and one with no record is at `self`. The headline shows the weakest separation among them, which act that is, and a count of acts at `apart` or better out of the number there must be. Anything resting on an act at `self` is at most `asserted`, whatever floor policy sets.

Trying again is recorded: a checker takes a ticket before each attempt, an attempt with no result counts as a failure, and the worst result on the current target counts. A pass after any earlier attempt along the same line that did not pass is flagged as retried and graded no higher than `helper`, whether or not the thing judged changed in between: a change does not reset the count or the cap, because a kernel cannot tell a real fix from a trivial change made to get a fresh try (decision 0024). The result itself is judged on the current target.

**Amendment.** Any difference from the baseline: a changed criterion, gate, limit, sample size, threshold, link to a check, or child. Granted only by the intent owner, recorded with what changed, why, by whom and at what separation, never erased. An amended criterion is at most `asserted` for the part amended. An amendment takes effect only at or above the separation floor policy sets; `apart` is the recommended floor.

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
12. A reviewer who says a check tests a criterion is right.
13. A declared separation level is true, and a harness that attests to one is honest and controls its own key.

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
