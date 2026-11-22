# Architecture claims

Each claim the architecture makes, the check that could show it false, and whether that check has run.

Status values:

- **checked**: every case of the check ran to completion with the expected outcome, including its planted defects, against the model files as they are now. The run is listed under [Recorded runs](#recorded-runs) and in [runs/index.json](runs/index.json); the repository checks fail if a claim is marked checked and its model files have changed since.
- **modelled, unchecked**: a model exists; no completed run is recorded.
- **not yet modelled**: the claim is only prose so far.

What a `checked` status means here, and no more:

- **Many of these properties still restate a rule.** A second review on 2026-11-18 found that most properties in seven rewritten models restated their own definitions ([log](../docs/reviews/2026-11-18-rewritten-models.md)). Issue 27 repaired six of them: each keeps a specification, stated over the history of events or every record, apart from a kernel working from what it stores, and adds planted defects for the direction a property did not check. Where the two sides still compute the same thing from equal values, the section says so under **What still restates the rule**; there `checked` means the rule is written down exactly and each planted defect listed is caught, not that the rule is right.
- A bounded model check shows a property for the bounds in the configuration, not for all sizes. Each section states its bounds.
- The models have one kernel, a ledger that keeps what it is given, and abstract hashes that never collide.
- Nothing here says anything about an implementation. That is a separate conformance obligation ([decision 0012](../decisions/0012-spec-to-code-conformance-is-an-explicit-seam.md)).

## Modelled in `kernel/EvidenceReuse.tla`

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C1 | Given a provider that is correct and declares all its inputs: a reported pass means the obligation holds for the current inputs, and a reported failure means it does not, under any interleaving of edits, tool changes, lost runs and completions | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Sound` | Key leaves out the tool digest; result filed under the key at completion | **checked**, run 9 |
| C2 | Every reusable record was produced by a run that completed; an unreachable backend never produces one | [0005](../decisions/0005-closed-verdict-set.md) | `Provenance` | Unavailable recorded as passed | **checked**, run 9 |
| C3 | With a correct provider, no evidence key ever holds both a pass and a failure | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Consistent` | Result filed under the key at completion | **checked**, run 9 |
| C4 | Even with a provider that can be wrong, a pass is never reported while a failure is recorded for the same key | [0005](../decisions/0005-closed-verdict-set.md) | `NoPassOverFail`, small instance | With conflicting records, the pass wins | **checked**, run 9 |
| C5 | The design does reuse records after a change that does not affect them, so C1 is not satisfied by rerunning everything | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | Reachability: `NeverReusedAfterChange` must be violated | (reachability) | **checked**, run 9 |
| C6 | C1 depends on two trusted-base assumptions: complete declared inputs, and a correct provider. Removing either breaks it | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Sound` must be violated in both cases | (the broken assumption is the check) | **checked**, run 9 |

C6 does not show the assumptions hold. It shows they are load-bearing, which is why they are in the [trusted base](../MODEL.md#6-trusted-base).

## Modelled in `intent/IntentGates.tla`

Bounds: one intent with two or three criteria (hard and deferred), at most one or two amendments, three separation levels.

This model is narrow. It takes a recorded separation level as given and checks only what the kernel does with it; whether the level is true is outside it. `DeliveredSound`, `DeliveredConfirmed`, `DeliveredGuarded` and `FulfilledSound` can only catch a kernel that computes the report wrongly. `GateProvenance` does not require the amendment to come before the change. Not covered: child intents, the text of criteria, assurance levels, time limits and checks that vary between runs.

The model was rewritten on 2026-11-17 to add the baseline, the unguarded rule and graded separation. Runs 3 and 4 were of earlier versions and support no current claim. Run 6 is of the current version, in which a level that is only declared counts as `helper` at most.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C23 | An intent is never reported delivered with a hard gate not passed, nor fulfilled with a deferred gate open | [0018](../decisions/0018-hard-soft-and-deferred-gates.md) | `DeliveredSound`, `FulfilledSound` | A hard gate whose check has not run is treated as passed; an open deferred gate does not block fulfilment | **checked**, run 9 |
| C25 | While an intent is confirmed, a gate differs from the baseline only through an amendment on record that took effect, and only the owner's amendments take effect | [0020](../decisions/0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md) | `GateProvenance`, `OnlyOwnerAmends` | A gate is edited and the intent stays confirmed; the worker's amendment takes effect | **checked**, run 9 |
| C28 | Amendments are live rules: a sufficiently separate owner's amendment can open the way to delivery, and one below the floor cannot | [0020](../decisions/0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md) | Reachability of delivery by amendment, and its absence when the grantor cannot reach the floor | (reachability) | **checked**, run 9 |
| C29 | An intent the owner has not confirmed, or that was edited since, is never reported delivered | [0017](../decisions/0017-intent-in-plain-words-broken-down.md) | `DeliveredConfirmed` | An unconfirmed intent is reported delivered | **checked**, run 9 |
| C30 | An intent with fewer hard gates than policy demands is never reported delivered. Children are not modelled | [0018](../decisions/0018-hard-soft-and-deferred-gates.md) | `DeliveredGuarded` | An intent with no hard gate is reported delivered | **checked**, run 9 |
| C33 | An act with no separation recorded is graded `self`, as is the worker granting to itself; an amendment below policy's floor does not take effect; the level reported is the level used | [0024](../decisions/0024-separation-is-graded-not-enforced.md) | `DefaultIsLowest`, `WorkerIsSelf`, `FloorHolds`, `LevelShown` | Nothing recorded treated as a high level; the worker keeps the level it wrote down; an amendment below the floor takes effect; a higher level shown than recorded | **checked**, run 9 |

## Modelled in `planner/Planner.tla`

Bounds: five definitions, two of them in one file; the depends-on relation one of two shapes with different closures, a chain three steps deep and a diamond; two hash values, a compiler and a test runner; every behaviour of at most six steps. Builds do not fail.

**How the properties get their content (repair, 2026-11-18).** The specification finds what a result depends on by following the relation until nothing new turns up, and the truth of a test is the artifact it actually ran on. The kernel builds its key from an index that follows the relation in a fixed number of passes, and looks artifacts up by key. The relation varies between behaviours, so a key that follows it wrongly shows. The properties compare the two in both directions: nothing wrongly reused, nothing current rerun, and everything without a right result planned. Their content is the index and the store.

**What still restates the rule.** For a check and a build, the key and the truth are equal by construction once the index finds the right closure; a test's truth is still taken from the store, looked up by the build key ([issue 33](https://github.com/sloik/dodona/issues/33)). With the design's plan, `PlanComplete` follows from `NoWrongReuse`; it has content against a planner that plans too little.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C9 | Nothing stale is reused, including what is stale through a dependency of a dependency of a dependency; with per-definition identity nothing current is rerun; and everything without a result resting on the current inputs is planned. A test is run only on the artifact built from the current inputs | [0002](../decisions/0002-small-kernel-everything-else-is-a-provider.md) | `NoWrongReuse`, `NoNeedlessRerun`, `PlanComplete` | The key follows one level of dependencies only, none, or too few passes for the chain; the test runs on whatever was built last; the planner reruns everything; the planner plans nothing | **checked**, run 9 |
| C8 | File-level fallback identity never causes a wrong reuse and plans everything that needs it. It does cause extra reruns, and that is shown too | [0004](../decisions/0004-definition-identity-comes-from-the-language-provider.md) | `NoWrongReuse` and `PlanComplete` with file identity; `NoNeedlessRerun` must be violated there | The fallback misses a dependency of a dependency | **checked**, run 9 |
| C10 | Changing a build tool makes what it built stale, and makes checks of what it built stale | [data model](../MODEL.md#3-obligations) | `NoWrongReuse` | A build's key leaves out the compiler; a test's key leaves out the build that produced what it tests | **checked**, run 9 |

## Modelled in `assurance/Assurance.tla`

Every combination of three links, each with one of six levels or unreported, and two planted defects, each passed, failed, unknown or absent.

**How the properties get their content (repair, 2026-11-18).** The specification takes the weakest of the three links as a set. The kernel goes along the chain one link at a time, keeping the weaker of what it has and the next link, and reads the scale from its own table. The kernel answers with a level's name, read on the true scale. The properties say the two always agree, and that what the kernel reports about planted defects is what the specification says in every case, in both directions.

**What still restates the rule.** The report about planted defects is the same expression on both sides; only its planted defects give it content. This is still a pure rule: the specification and the kernel are two ways of writing it, and the model is meant to show they agree, once a run is recorded and that each way of getting the kernel's version wrong is caught. It cannot show the rule is the right one.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C24 | The shown level of a criterion is the weakest of its evidence links | [0019](../decisions/0019-assurance-is-stated-per-link.md) | `WeakestLink` | The links are averaged; the level is always the lowest; the middle link is skipped; the kernel's scale puts observed above sampled | **checked**, run 9 |
| C31 | A link with nothing reported counts as none and never raises the level | [0019](../decisions/0019-assurance-is-stated-per-link.md) | `WeakestLink` | A link nobody reported is left out | **checked**, run 9 |
| C19 | A check is reported as shown able to fail exactly when it has planted defects and every one was caught; with none planted it says so, and with one missed it says that | [data model](../MODEL.md#3-obligations) | `NonVacuitySound` | A planted defect that never ran counts as caught; a check with none planted is reported as shown; a check whose planted defect was missed is reported as having none | **checked**, run 9 |

## Modelled in `tree/IntentTree.tla`

Bounds: a root and one child, two criteria each, hard or soft; floors of one and two hard gates; at most six changes of shape or confirmations. One level of children; no exceptions, no deferred gates.

**Settled (repair, 2026-11-18; decision 0030).** The data model counts an intent's gates over its descendants, and decision 0017 says moving a criterion into a child loses nothing. So the policy's number is counted over the whole tree, and a child is not held to it on its own; every intent in the tree, each child included, must have at least one hard gate. Holding each child to the policy's number is a planted defect.

**How the properties get their content.** The specification decides confirmation from the order of events (the last confirmation came after the last change of shape) and counts gates from the tree as it is. The kernel keeps one flag, cleared on each change, and a running count of hard gates per intent, updated on each change. The properties say the kernel's confirmation and delivery are exactly the ones the specification calls for, both ways.

**What still restates the rule.** Both sides use the same test of whether every hard gate passes, so a kernel that judged a passing gate wrongly would be wrong on both sides.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C34 | A tree is delivered exactly when it is confirmed since its last change of shape, the whole tree counts at least the hard gates policy demands, every intent in it has a hard gate, and every hard gate passes. Adding or removing a child, or changing a gate, needs confirming again | [0030](../decisions/0030-the-hard-gate-floor-is-counted-over-the-tree.md) | `ConfirmationMatches`, `DeliveryMatches` | A child is removed or added, or a gate edited, and the confirmation stays; an unconfirmed tree is delivered; the root is delivered whatever its child is; a child with no hard gate counts as delivered; the floor is ignored, applied to each child, or counted without the child; the running count keeps a removed child or misses a child's edit | **checked**, run 9 |

## Modelled in `attempts/Attempts.tla`

Bounds: at most three attempts and two changes of target; the history of events kept in full. Attempts made without taking a ticket leave no record and are outside the model.

**Settled (repair, 2026-11-18; owner direction, decision 0031).** The data model capped only unchanged work; decision 0024 said a trivial change must not reset the count. The owner chose: shopping on the same target is capped at helper; after a change of target a retried agreement keeps its grade until the line has as many attempts that did not agree as policy allows (two by default), and is capped from then on. The result starts again on a new target. Capping every retry, and ignoring the limit, are planted defects.

**How the properties get their content.** The specification is stated over the history of events in the order they happened. The kernel works from its records, one per ticket, updated in place. The properties say the kernel's answers from its records are the ones the history calls for. A kernel that closes the wrong ticket, files an attempt under the target it has when it closes, or forgets attempts when the target changes, is caught even though its answers are computed by the right rule.

**What still restates the rule.** Given records that mirror the history, the result, shopping and retrying are the same expressions on both sides; their content is in how the records are kept. Retrying is worked out from the attempts as they stand, so closing an earlier open attempt as agreed clears the flag.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C35 | On the current target the worst result counts and an attempt left open is a failure. Along the whole line, whatever happened to the target, every attempt is counted, and an agreement after any earlier attempt that did not agree, as the attempts stand now, is reported as retried. It is graded helper at most when shopped on the same target, or when the line has reached the policy's limit of attempts that did not agree; never above what it claimed | [0031](../decisions/0031-an-agreement-after-a-real-change-keeps-its-grade-up-to-a-limit.md) | `WorstCounts`, `RetryIsCapped`, `HistoryIsKept` | Only the latest attempt counts; an open attempt is ignored; the wrong ticket is closed; an attempt is filed under the target at closing; retrying is not reported, or only on the same target; shopping is not flagged; the cap is ignored, applied to every retry, applied without the limit, or one refusal late; the cap raises a level; a change of target forgets attempts | **checked**, run 9 |

## Modelled in `platforms/Platforms.tla`

Bounds: two sets of inputs and three platforms; each platform may record each verdict once, so a platform can disagree with itself.

**Settled (repair, 2026-11-18): the claim is verified for each key.** The data model and the architecture say a result stands in for another platform only when the same key agrees on at least two platforms; decision 0008 says only "checked on two". The model had decided "verified" once for everything, so one key's agreement let another key's single record stand in. That is now a planted defect.

**How the properties get their content.** The specification is stated over every record ever made. The kernel works from what it has filed for each key and platform, updated one record at a time. The properties say every status, every report of a stand-in and every reproducibility answer is the one the records call for.

**What still restates the rule.** Unless a record is filed wrongly, the kernel's store equals what the records say, and status, verification and reproducibility are the same expressions on both sides. Their content is in the filing (one planted defect) and in each planted defect of the rule being caught. Any disagreement about the key, a platform's with itself included, cancels verification, even where two other platforms agree. That is stricter than "two agreeing platforms" read alone, and is now written down as [decision 0032](../decisions/0032-a-stand-in-is-verified-for-its-own-key-and-any-disagreement-withdraws-it.md).

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C15 | A platform's own records decide its status, and both verdicts are a conflict. A status with no record of its own exists only when policy allows stand-ins, the provider claims platform independence and that key has one verdict on at least two platforms; it is then that verdict, reported as a stand-in. Reproducibility differs on any disagreement, a platform's with itself included, agrees with at least two agreeing platforms, and is otherwise unknown | [0008](../decisions/0008-reproducibility-levels.md) | `StatusMatches`, `StandInIsReported`, `ReproMatches` | A record always stands in; stands in unverified, unclaimed, or verified by another key; a stand-in is always passed; another platform's record overrides a platform's own; a platform with both verdicts is passed; only the latest verdict is filed; a stand-in is not reported; one platform alone reproduces; a disagreement is ignored | **checked**, run 9 |

## Modelled in `decisions/Decisions.tla`

Bounds: three names, two of them governed by one decision; two contents and absence. No renaming.

The model keeps what the decision was last reviewed against apart from what the kernel has stored, so a kernel that quietly updates its stored value is caught. **Repair, 2026-11-18:** planted defects now flag too much as well as too little, so both halves of "exactly" are shown able to fail.

**What still restates the rule.** In the design, what the kernel has stored always equals what the decision was reviewed against, so `FlagIsExact` comes down to that equality; its content is in the planted defects.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C16 | A decision is flagged exactly when some name it governs no longer has the content the decision was last reviewed against, including when the name is gone, and whether or not the old content exists elsewhere | [0001](../decisions/0001-decisions-are-nodes.md) | `FlagIsExact` | The kernel tracks contents without names; a name that disappears is not flagged; the stored content is refreshed on every edit; only the first governed name is watched; a name it does not govern flags it; the flag stays after the content is changed back | **checked**, run 9 |

## Modelled in `liveness/Liveness.tla`

Bounds: one obligation, which can or cannot be checked, fixed from the start; at most two edits, two outages and two runs that end without finishing.

**The claim holds only under five assumptions, and they carry most of its weight**: the kernel keeps submitting whatever has no answer; the backend comes back after an outage; a run in flight ends, and once the allowed number of errors and losses is used up every run that is started completes with its answer; edits, outages, errors and losses each happen only a bounded number of times; and the kernel can tell that a run was lost. The third is stronger than "a run ends one way or another", and the model's header now says so. A run that hangs silently for ever is outside the model. No scenario in the conformance kit covers this, because the seed kernel has no loop that submits work.

**Repair (issue 27, 2026-11-18).** `EventuallyAnswered` says an answer comes; it accepted a kernel that gives up early by calling a retryable failure "unsupported", since that is an answer too. `AnswerIsRight` checks the other direction: "unsupported" is given only for an obligation that cannot be checked, with a planted defect that gives up on an error. **What still restates the rule:** the only thing of the kernel's that `EventuallyAnswered` tests is which outcomes it tries again after; fairness and the bounds do the rest. `AnswerIsRight` restates how the model's `Complete` decides an answer; its content is the planted defect. That `EventuallyAnswered` accepts the give-up defect is argued from the model (a run that errs has no fairness, so it may give up), not run as a case.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C22 | Under those assumptions, the one obligation in the model eventually has a verdict or the stated reason that it cannot be checked, that then stays, and the stated reason is given only when it is true | [0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md) | `EventuallyAnswered`, `AnswerIsRight` | After finding the backend down, after a lost run, or after an error, the kernel never tries again; an obligation that cannot be checked is submitted again and again; an error is reported as unsupported | **checked**, run 10 |

## Checked against the seed kernel

| # | Claim | Decision | Check | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C37 | Both kernels give the model's own answer on every state the two dump models reach: the status of each obligation, and for an intent whether it is delivered or fulfilled and how each exception request is graded | [0025](../decisions/0025-the-first-seed-kernel.md) | `tools/check_states.py` over the model checker's list of states; recorded from a development machine, and repeated in CI on every change to main | Each of five defects planted in the first kernel made between 1,515 and 34,020 states disagree (an earlier run, [review](../docs/reviews/2026-11-17-kit-and-seed.md)); not repeated for this record | **checked**, run 13 |

Run 13 records the current comparison. Runs 9, 11 and 12 remain the records for the earlier input bundles. The comparison ties the code to the models for all states within the bounds of the dump models, which are smaller than the main ones: for evidence, two obligations, one run in flight and at most three records; for intents, two criteria and one exception. It says nothing about what the models do not cover.

## Shown by the conformance kit, not by a model

These claims are not checked by a model. Each is exercised on every change by the tools named, on the kernels that exist. That is evidence at the level `sampled`: it shows the cases that were tried. None of these counts as checked.

| # | Claim | Decision | Exercised by | What that does and does not show | Status |
|---|---|---|---|---|---|
| C7 | The same content has the same identity on every platform, and a path is accepted on all platforms or none | [0004](../decisions/0004-definition-identity-comes-from-the-language-provider.md), [0009](../decisions/0009-platform-order-and-portability-rules.md) | `tools/run_vectors.py`, `tools/run_path_vectors.py`, `tools/path_differential.py` | The vectors and random paths that were tried, on macOS, Linux and Windows. Not every content or path. Only the kernels that were judged | sampled by the kit |
| C13 | No malformed, late or out-of-order provider message leads to a pass | [0003](../decisions/0003-providers-are-separate-processes.md) | `tools/run_provider_cases.py`, `tools/run_check_cases.py` | Both kernels and the stage-0 reference hosts, against a provider and a checker that break one rule at a time, judged from what the provider and the executor record of what the host sent them, against what the contract says it must send; a host written to forge those records is not caught ([decision 0033](../decisions/0033-a-kernel-hosts-providers.md)). Late and out-of-order messages across several requests in flight are not covered, nor is a process that deliberately leaves the provider's process group or job | sampled by the kit |
| C18 | A record no trusted kernel wrote is never reused; a torn ledger write never changes a status silently | [0015](../decisions/0015-ledger-integrity-and-record-trust.md) | `tools/run_ledger_cases.py`, `tools/run_kit.py` | A ledger damaged in each listed way, cut at every byte of its last entry, and written by two kernels at once; and status scenarios with records from another writer, another platform and a key that does not match. A crash in the middle of a write is imitated by cutting the file, not caused | sampled by the kit |
| C20 | The conformance kit rejects kernels with known defects. The current inventory lists 275 in the first kernel and 319 in the second. A complete rerun of this inventory is pending. | [0011](../decisions/0011-self-hosting-through-a-verified-seed.md) | `tools/kit_adequacy.py`, `kernel2/plant.js` | Earlier reports credited 216 and 244 catches respectively. Those runs could count judge crashes as catches. Issue 41 tracks false catches and completed named results. Coverage extends to defects listed by the authors and reviewers. | sampled by the kit |
| C36 | A separation level is never shown without its weakest source, and a fact not covered by a valid attestation is treated as declared | [0024](../decisions/0024-separation-is-graded-not-enforced.md) | `tools/run_kit.py`, `tools/run_attest_check.py`, `tools/run_harness_check.py` | Kernels grading act records: check values written into the kit, others made at test time, and records a reference harness signs after really starting a checker. The key is a published fixture, and the reference harness reads it from a file the working agent could read too, so nothing real is vouched for | sampled by the kit |
| C21 | Two independent kernels agree on real project states, and any disagreement is reported as a conflict | [0011](../decisions/0011-self-hosting-through-a-verified-seed.md) | `tools/kernel_differential.py`, `tools/run_kit.py` | Two kernels, in Rust and JavaScript, the second written without sight of the first, give the same full answers on every scenario and on reshuffled ones. Not on real project states at scale, and a disagreement is reported by the tool, not yet by a kernel as a conflict. Each kernel was written in a fresh context, without sight of the other, with one exception recorded in the README: while the hosts were reworked, the first kernel's author was shown a list quoting lines of the second kernel's host code; both authors are the same make of AI model as the kit's, which a project may or may not want | sampled by the kit |


The previous PR 40 Rust run reached its three-hour limit without a tally. The JavaScript run completed, but counted one ledger defect when the judge exited without a mismatch. The Rust inventory now runs in eight shards and requires all of them to complete successfully. The inventories remain 275 Rust and 319 JavaScript defects. [Cancelled Rust job](https://github.com/sloik/dodona/actions/runs/44937841949/job/136948287145) · [Earlier JavaScript job](https://github.com/sloik/dodona/actions/runs/44937841949/job/136948286911).

On 2026-11-22, a local Rust shard containing one defect completed with one catch and reported only shard success. The held-lock JavaScript defect reproduced the old judge's cleanup failure. With the fixture repair, the same defect produced a named held-lock mismatch and a completed 110-case tally. Both unchanged kernels matched all 110 ledger and 253 project-status cases, and the reference matched all 103 project-run cases. The repository's new controls failed before their corresponding fixes and the full repository checker then completed successfully. These are self checks for PR 40. Full hosted mutation results and issue 41's named evidence remain pending.

## Not yet modelled

| # | Claim | Decision | Intended check | Planted defect that must fail |
|---|---|---|---|---|
| C11 | A check never runs on an executor the configuration did not name, and a mismatch between requested and reported tools or platform is never a result | [0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md) | Model, plus scenarios with the executor down and with a lying executor | Kernel with a silent local fallback |
| C12 | A run is not submitted twice and not lost across a kernel restart | [0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md) | Model with handles and restart | Kernel that resubmits on restart |
| C14 | Adding a platform to the lock changes no existing entry | [0008](../decisions/0008-reproducibility-levels.md) | Scenario: resolve on one platform, add a second | Resolver that re-resolves existing entries |
| C17 | A change that weakens policy is always visible in the report | [0014](../decisions/0014-policy-is-separate-from-configuration.md) | Scenarios: lowered bound, removed obligation, weaker provider | Kernel that judges against the edited policy only |
| C26 | A varying check is never reported from fewer runs than it declared | [0018](../decisions/0018-hard-soft-and-deferred-gates.md) | Scenarios with declared sample sizes | Kernel that stops at the first passing run |
| C27 | Two intents that touch the same definition are reported as colliding before work starts | [0017](../decisions/0017-intent-in-plain-words-broken-down.md) | Scenarios | Index that compares declared paths only as text |
| C32 | A status is never shown without its headline, and a self-granted exception or unverified independence is always in it | [0019](../decisions/0019-assurance-is-stated-per-link.md), [0020](../decisions/0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md) | Scenarios on the agent interface | Interface that returns the status word alone |

## Recorded runs

### Run 1: `kernel/EvidenceReuse.tla`, 2026-11-17

Checker: TLC2 Version 2.19 of 08 August 2024 (rev: 5a47802), from tla2tools 1.7.4, one worker. Model files (SHA-256): `EvidenceReuse.tla` `3d4b878a24d6e96d925b4c7d0406041eb42648974db8a59b4792a2d480312c20`, `MC.tla` `85f57a901972d333d7939e49da4d89a91851c09c6cd26e1a0b6ec060b5b56c8c`. The checker and the runtime under it are not pinned by digest yet.

13 of 14 cases matched. **The main design case did not complete** in this run; see run 2.

| Case | Expected | Result | States generated / distinct | Match |
|---|---|---|---|---|
| `design` | no violation | **did not complete**: the checker ran out of its disk allowance after 2,581,743 distinct states, with 310,237 still to explore and no violation found so far | 17,611,514 / 2,581,743 | no |
| `design_three_hashes` | no violation | no violation, search complete | 1,660,815 / 202,428 | yes |
| `design_flaky` | no violation | no violation, search complete | 315,212 / 38,704 | yes |
| `reach_pass` | `NeverPassed` violated | violated | 68 / 37 | yes |
| `reach_fail` | `NeverFailed` violated | violated | 88 / 47 | yes |
| `reach_reuse` | `NeverReusedAfterChange` violated | violated | 249 / 130 | yes |
| `reach_conflict` | `NeverConflict` violated | violated | 274 / 134 | yes |
| `mutant_key_omits_tool` | `Sound` violated | violated | 230 / 120 | yes |
| `mutant_complete_with_current_key` | `Sound` violated | violated | 223 / 117 | yes |
| `mutant_complete_with_current_key_consistent` | `Consistent` violated | violated | 2,904 / 1,190 | yes |
| `mutant_unavailable_is_pass` | `Provenance` violated | violated | 61 / 33 | yes |
| `mutant_pass_outranks_fail` | `NoPassOverFail` violated | violated | 274 / 134 | yes |
| `assumption_undeclared_dep` | `Sound` violated | violated | 266 / 140 | yes |
| `assumption_flaky_provider` | `Sound` violated | violated | 33 / 16 | yes |

Every violation ended with the checker's exit code 12 and every completed search with 0. The incomplete case ended with 255.

What this run establishes: C4, C5 and C6, which need only the small instance or a violation. For C1 to C3 it establishes that each planted defect is caught, and that the properties hold on the small three-hash instance; it does not establish them at the main bounds.

### Run 2: the main design case, 2026-11-17

Same checker, same `EvidenceReuse.tla` and `MC.tla` as run 1, with root module `MCDesign.tla` (SHA-256 `0506b653fb859765ffbbb46ce34e713137826240c571361ba9792228eff3439b`) and `design.cfg` (`c214becbb3978d011b9d1f890f9f84d967858aeede311d85fcf46ec0edaaa451`). The bounds are unchanged. The only difference from run 1 is a state view that leaves out the history variable `changed`, which none of the checked properties read and no action uses to decide anything else; the reasoning is in `MCDesign.tla`.

| Case | Expected | Result | States generated / distinct | Match |
|---|---|---|---|---|
| `design` | no violation of `TypeOK`, `Sound`, `Provenance`, `Consistent`, `NoPassOverFail` | no violation, search complete, depth 33 | 12,599,304 / 1,540,096 | yes |

With run 1, all 14 cases of this model matched. C1 to C6 were checked on that basis, for the bounds and assumptions stated at the top of this file, and for the model only.

The soundness of using a state view was an argument, not something the checker verified. Run 5 repeats the case without the view, so nothing rests on that argument any more.

### Run 3: `intent/IntentGates.tla`, 2026-11-17 (superseded)

**This run was of an earlier version of the model. The model has since been rewritten, so this run supports no current claim.** It is kept as a record.

Checker: TLC2 Version 2.19 of 08 August 2024 (rev: 5a47802), one worker. Model files (SHA-256): `IntentGates.tla` `164207df042124401ac7e40852621eb6ef8d25eec9ff9f2b983da53216039cfa`, `MC.tla` `858ad6b8f3cbb0b0efae74ac7a6dc208b248a3b955de0b5866b68d7cf1e7f9a5`.

All 13 cases matched.

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design_separate_owner` | no violation | no violation, search complete | 11,989 / 999 |
| `design_same_party_strict` | no violation | no violation, search complete | 7,129 / 594 |
| `design_same_party_lenient` | no violation | no violation, search complete | 11,989 / 999 |
| `strict_blocks_self_amendment` | no violation | no violation, search complete | 7,129 / 594 |
| `reach_delivered` | `NeverDelivered` violated | violated | 15 / 14 |
| `reach_fulfilled` | `NeverFulfilled` violated | violated | 160 / 86 |
| `reach_delivered_by_amendment` | `NeverDeliveredByAmendment` violated | violated | 22 / 20 |
| `mutant_worker_can_amend` | `OnlyOwnerAmends` violated | violated | 20 / 14 |
| `mutant_self_counts` | `NoSelfWhenIndependent` violated | violated | 8 / 8 |
| `mutant_hide_self` | `SelfShown` violated | violated | 8 / 8 |
| `mutant_silent_change` | `GateProvenance` violated | violated | 14 / 14 |
| `mutant_delivered_ignores_unknown` | `DeliveredSound` violated | violated, in the initial state | not reported by the checker |
| `mutant_deferred_as_passed` | `FulfilledSound` violated | violated | 15 / 14 |

A defect in the judge, found by this run: `tools/check_models.py` at first reported `mutant_delivered_ignores_unknown` as a mismatch. The checker had found the right property violated, and words a violation in the very first state differently. The judge was corrected to accept that wording for the named property only, with tests that a different or longer property name is still rejected. The mismatch was a fault in the judge, not in the model or the expectation.

This model is narrow, as said above. "Checked" here means these few rules hold in a model that takes the declared gates and the identities of the parties as given.

### Run 4: `intent/IntentGates.tla` as rewritten, 2026-11-17

Checker: TLC2 Version 2.19 of 08 August 2024 (rev: 5a47802), one worker. Model files (SHA-256): `IntentGates.tla` `5896839e889b178ed042599f8b2a7bf2f790dcc2f897832bd5f6c844b30dd166`, `MC.tla` `54684b83b7db18a142623ec57e894d8caea05181c6958966161d5a4dc064f266`.

All 17 cases matched: 4 searches completed with no violation, 3 behaviours were shown reachable, and each of the 10 planted defects was caught by the property aimed at it.

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design_three_criteria` | no violation | no violation, search complete | 22,134,628 / 1,494,450 |
| `design_two_criteria` | no violation | no violation, search complete | 12,170,818 / 969,246 |
| `design_low_floor` | no violation | no violation, search complete | 14,153,698 / 1,018,818 |
| `floor_blocks_weak_grantor` | no violation | no violation, search complete | 15,997,906 / 1,122,660 |
| `reach_delivered` | `NeverDelivered` violated | violated | 237 / 137 |
| `reach_fulfilled` | `NeverFulfilled` violated | violated | 4,617 / 1,255 |
| `reach_delivered_by_amendment` | `NeverDeliveredByAmendment` violated | violated | 297 / 169 |
| `mutant_worker_can_amend` | `OnlyOwnerAmends` violated | violated | 59 / 39 |
| `mutant_worker_keeps_level` | `WorkerIsSelf` violated | violated | 59 / 39 |
| `mutant_below_floor_counts` | `FloorHolds` violated | violated | 55 / 35 |
| `mutant_missing_is_apart` | `DefaultIsLowest` violated | violated | 79 / 59 |
| `mutant_hide_level` | `LevelShown` violated | violated | 55 / 35 |
| `mutant_edit_keeps_confirmation` | `GateProvenance` violated | violated | 51 / 35 |
| `mutant_draft_delivers` | `DeliveredConfirmed` violated | violated | 2 / 2 |
| `mutant_unguarded_delivers` | `DeliveredGuarded` violated | violated | 56 / 36 |
| `mutant_delivered_ignores_unknown` | `DeliveredSound` violated | violated | 6 / 6 |
| `mutant_deferred_as_passed` | `FulfilledSound` violated | violated | 15 / 13 |

This model is narrow, as said above. "Checked" here means these rules hold in a small model that takes a recorded separation level as given; whether a recorded level is true is outside it.

### Run 5: the main design case without a state view, 2026-11-17

Same checker and the same `EvidenceReuse.tla` and `MC.tla` as run 1; `design.cfg` (SHA-256 `5f767efdef33fd97ff843ae08cea81f6bce6d35150856d51faf0a9f76e4ce9b0`) at the main bounds with no state view. It could not complete before because one of the checker's working files exceeded the size allowed to a job; the project now has its own allowance.

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no violation of `TypeOK`, `Sound`, `Provenance`, `Consistent`, `NoPassOverFail` | no violation, search complete, depth 34 | 27,385,032 / 3,575,936 |

C1 to C3 now rest on runs 1 and 5. The state view and its module have been removed from the repository; run 2 is kept as a record.

### Run 6: every model, in CI, 2026-11-17

The first complete run by the project's own workflow, on its own runner: [run 44164593817](https://github.com/sloik/dodona/actions/runs/44164593817), commit `a4862ea`. All cases went to the executor as one job. Checker: TLC2 Version 2.19 of 08 August 2024 (rev: 5a47802), one worker. The model files are identified by hash in [runs/index.json](runs/index.json), and the checker's raw output for every case is under `runs/run-6/`.

**75 of 75 cases matched.** Every earlier run is superseded by this one.

A second job then ran the seed kernel over the model checker's lists of states: **71,744 states of the evidence model and 78,894 of the intent model, with no difference.**

Two earlier attempts at this run stopped partway, at a limit on the space a job may use: first the model checker's leftover working files, then a list of states that was too large. Every case that ran in them matched. Neither is counted.

**`assurance`** (8 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 24,696 / 12,348 |
| `reach_proven` | violation | violation of NeverProven | not reported |
| `reach_shown` | violation | violation of NeverShown | not reported |
| `mutant_average` | violation | violation of WeakestLink | not reported |
| `mutant_ignore_unreported` | violation | violation of WeakestLink | not reported |
| `mutant_unknown_defect_counts` | violation | violation of NonVacuitySound | not reported |
| `mutant_empty_is_shown` | violation | violation of NonVacuitySound | not reported |
| `mutant_always_nothing` | violation | violation of NotUnderstated | not reported |

**`attempts`** (7 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 412 / 182 |
| `reach_agreed` | violation | violation of NeverAgreed | 5 / 5 |
| `reach_shopped` | violation | violation of NeverShopped | 11 / 11 |
| `mutant_latest_only` | violation | violation of WorstCounts | 11 / 11 |
| `mutant_open_ignored` | violation | violation of WorstCounts | 10 / 10 |
| `mutant_flag_does_not_cap` | violation | violation of ShoppingIsFlagged | 11 / 11 |
| `mutant_flag_missed` | violation | violation of ShoppingIsFlagged | 11 / 11 |

**`decisions`** (4 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 82 / 18 |
| `reach_flagged` | violation | violation of NeverFlagged | 5 / 5 |
| `mutant_identities_without_names` | violation | violation of FlagIsExact | 5 / 5 |
| `mutant_gone_is_not_flagged` | violation | violation of FlagIsExact | 5 / 5 |

**`intent`** (18 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design_three_criteria` | no-violation | no-violation | 48,990,988 / 2,964,114 |
| `design_two_criteria` | no-violation | no-violation | 59,977,018 / 3,803,598 |
| `design_low_floor` | no-violation | no-violation | 76,469,914 / 4,032,666 |
| `floor_blocks_weak_grantor` | no-violation | no-violation | 34,565,536 / 2,224,908 |
| `reach_delivered` | violation | violation of NeverDelivered | 285 / 185 |
| `reach_fulfilled` | violation | violation of NeverFulfilled | 12,729 / 2,167 |
| `reach_delivered_by_amendment` | violation | violation of NeverDeliveredByAmendment | 393 / 265 |
| `mutant_worker_can_amend` | violation | violation of OnlyOwnerAmends | 59 / 39 |
| `mutant_worker_keeps_level` | violation | violation of WorkerIsSelf | 59 / 39 |
| `mutant_below_floor_counts` | violation | violation of FloorHolds | 55 / 35 |
| `mutant_missing_is_apart` | violation | violation of DefaultIsLowest | 79 / 59 |
| `mutant_hide_level` | violation | violation of LevelShown | 55 / 35 |
| `mutant_edit_keeps_confirmation` | violation | violation of GateProvenance | 51 / 35 |
| `mutant_draft_delivers` | violation | violation of DeliveredConfirmed | 2 / 2 |
| `mutant_unguarded_delivers` | violation | violation of DeliveredGuarded | 88 / 68 |
| `mutant_delivered_ignores_unknown` | violation | violation of DeliveredSound | 6 / 6 |
| `mutant_deferred_as_passed` | violation | violation of FulfilledSound | 15 / 13 |
| `mutant_declared_counts_in_full` | violation | violation of DeclaredIsCapped | 55 / 35 |

**`kernel`** (14 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 27,385,032 / 3,575,936 |
| `design_three_hashes` | no-violation | no-violation | 1,660,815 / 202,428 |
| `design_flaky` | no-violation | no-violation | 315,212 / 38,704 |
| `reach_pass` | violation | violation of NeverPassed | 68 / 37 |
| `reach_fail` | violation | violation of NeverFailed | 88 / 47 |
| `reach_reuse` | violation | violation of NeverReusedAfterChange | 249 / 130 |
| `reach_conflict` | violation | violation of NeverConflict | 274 / 134 |
| `mutant_key_omits_tool` | violation | violation of Sound | 230 / 120 |
| `mutant_complete_with_current_key` | violation | violation of Sound | 223 / 117 |
| `mutant_complete_with_current_key_consistent` | violation | violation of Consistent | 2,904 / 1,190 |
| `mutant_unavailable_is_pass` | violation | violation of Provenance | 61 / 33 |
| `mutant_pass_outranks_fail` | violation | violation of NoPassOverFail | 274 / 134 |
| `assumption_undeclared_dep` | violation | violation of Sound | 266 / 140 |
| `assumption_flaky_provider` | violation | violation of Sound | 33 / 16 |

**`liveness`** (3 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 452 / 191 |
| `mutant_no_resubmit_after_unavailable` | temporal-violation | temporal violation | 416 / 191 |
| `mutant_no_resubmit_after_loss` | temporal-violation | temporal violation | 292 / 139 |

**`planner`** (8 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design_definition` | no-violation | no-violation | 108,736 / 15,968 |
| `design_file` | no-violation | no-violation | 685,760 / 99,488 |
| `file_costs_reruns` | violation | violation of NoNeedlessRerun | 259 / 99 |
| `reach_all_current` | violation | violation of NeverAllCurrent | 692 / 329 |
| `mutant_direct_deps_only` | violation | violation of NoWrongReuse | 258 / 98 |
| `mutant_fallback_direct_deps_only` | violation | violation of NoWrongReuse | 258 / 98 |
| `mutant_key_omits_producer` | violation | violation of NoWrongReuse | 714 / 338 |
| `mutant_plan_everything` | violation | violation of NoNeedlessRerun | 38 / 33 |

**`platforms`** (7 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design_stand_in_allowed` | no-violation | no-violation | 217 / 81 |
| `design_stand_in_forbidden` | no-violation | no-violation | 217 / 81 |
| `reach_stand_in` | violation | violation of NeverStoodIn | 58 / 34 |
| `mutant_always_stand_in` | violation | violation of StandInIsEarned | 2 / 2 |
| `mutant_stand_in_unverified` | violation | violation of StandInIsEarned | 2 / 2 |
| `mutant_one_platform_reproduces` | violation | violation of ReproSound | 2 / 2 |
| `mutant_disagreement_ignored` | violation | violation of ReproSound | 14 / 14 |

**`tree`** (6 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 341,312 / 28,512 |
| `reach_delivered` | violation | violation of NeverDelivered | 1,710 / 943 |
| `mutant_remove_keeps_confirmation` | violation | violation of ShapeIsConfirmed | 1,642 / 929 |
| `mutant_add_keeps_confirmation` | violation | violation of ShapeIsConfirmed | 498 / 465 |
| `mutant_delivered_ignores_children` | violation | violation of TreeSound | 147 / 147 |
| `mutant_soft_child_is_delivered` | violation | violation of TreeSound | 2,163 / 1,134 |

### Run 7, kernel: the kernel again, on run 6's states

2026-11-18. The seed kernel was extended, so its agreement with the two dump models was measured again on the state lists run 6 wrote out: 71,744 and 78,894 states, no difference. The second kernel agrees on the same states. No model was run for this.

### Run 7: three of the rewritten models

2026-11-18. The planner, platforms and tree models as rewritten after the review, run through the shared queue from a development machine: platforms and tree in job `8d41ae3f84254c84b62384ef67d84fbc`, the planner in job `f1e82dbabf9d42e0940ed943d1e3a3ae` after one of its defect cases was found to compare values of two kinds and was corrected. Both jobs completed. Outputs: [runs/run-7/](runs/run-7/). The other four rewritten models ran in run 8.

**`planner`** (10 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design_definition` | no-violation | no-violation | 19,951 / 8,988 |
| `design_file` | no-violation | no-violation | 29,378 / 15,161 |
| `file_costs_reruns` | violation | violation of NoNeedlessRerun | 60 / 40 |
| `reach_all_current` | violation | violation of NeverAllCurrent | 321 / 172 |
| `mutant_direct_deps_only` | violation | violation of NoWrongReuse | 61 / 40 |
| `mutant_no_deps` | violation | violation of NoWrongReuse | 59 / 39 |
| `mutant_fallback_direct_deps_only` | violation | violation of NoWrongReuse | 61 / 41 |
| `mutant_key_omits_producer` | violation | violation of NoWrongReuse | 354 / 186 |
| `mutant_test_without_build` | violation | violation of NoWrongReuse | 330 / 178 |
| `mutant_plan_everything` | violation | violation of NoNeedlessRerun | 8 / 8 |

**`platforms`** (12 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design_stand_in_allowed` | no-violation | no-violation | 2,917 / 729 |
| `design_stand_in_forbidden` | no-violation | no-violation | 2,917 / 729 |
| `design_not_claimed` | no-violation | no-violation | 2,917 / 729 |
| `reach_stand_in` | violation | violation of NeverStoodIn | 15 / 15 |
| `mutant_always_stand_in` | violation | violation of StandInIsEarned | 2 / 2 |
| `mutant_stand_in_unverified` | violation | violation of StandInIsEarned | 2 / 2 |
| `mutant_stand_in_unclaimed` | violation | violation of StandInIsEarned | 15 / 15 |
| `mutant_stand_in_always_passed` | violation | violation of StandInIsEarned | 80 / 60 |
| `mutant_other_overrides_own` | violation | violation of OwnRecordDecides | 20 / 20 |
| `mutant_stand_in_not_reported` | violation | violation of StandInIsReported | 15 / 15 |
| `mutant_one_platform_reproduces` | violation | violation of ReproSound | 2 / 2 |
| `mutant_disagreement_ignored` | violation | violation of ReproSound | 20 / 20 |

**`tree`** (10 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 341,312 / 28,512 |
| `design_floor_two` | no-violation | no-violation | 341,312 / 28,512 |
| `reach_delivered` | violation | violation of NeverDelivered | 1,710 / 943 |
| `reach_delivered_floor_two` | violation | violation of NeverDelivered | 10,531 / 3,482 |
| `mutant_remove_keeps_confirmation` | violation | violation of ShapeIsConfirmed | 1,642 / 929 |
| `mutant_add_keeps_confirmation` | violation | violation of ShapeIsConfirmed | 498 / 465 |
| `mutant_delivered_ignores_children` | violation | violation of TreeSound | 147 / 147 |
| `mutant_soft_child_is_delivered` | violation | violation of TreeSound | 2,163 / 1,134 |
| `mutant_ignores_floor` | violation | violation of TreeGuarded | 51 / 51 |
| `mutant_floor_counts_root_only` | violation | violation of TreeComplete | 10,531 / 3,482 |

### Run 8: every model, through the provider

2026-11-18. [CI run 44201829244](https://github.com/sloik/dodona/actions/runs/44201829244) on commit `216076c`. The first run in which dodona's own provider described the checks: 94 cases of the nine models as one job on the shared queue, which completed; 94 matched. The executor measured the checker it ran, and it is byte for byte the upstream release 1.7.4. The verdicts were written to a ledger by the seed kernel, which then reported the status of this project: `draft` for every intent and `unknown` for the project, because nothing is confirmed and the tools were not pinned when it ran. The four models below had no completed run before this one. Outputs: [runs/run-8/](runs/run-8/).

**`assurance`** (8 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 24,696 / 12,348 |
| `reach_proven` | violation | violation of NeverProven |  |
| `reach_shown` | violation | violation of NeverShown |  |
| `mutant_average` | violation | violation of WeakestLink |  |
| `mutant_ignore_unreported` | violation | violation of WeakestLink |  |
| `mutant_unknown_defect_counts` | violation | violation of NonVacuitySound |  |
| `mutant_empty_is_shown` | violation | violation of NonVacuitySound |  |
| `mutant_always_nothing` | violation | violation of NotUnderstated |  |

**`attempts`** (11 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 1,236 / 516 |
| `design_claims_self` | no-violation | no-violation | 1,236 / 516 |
| `reach_agreed` | violation | violation of NeverAgreed | 5 / 5 |
| `reach_shopped` | violation | violation of NeverShopped | 12 / 12 |
| `reach_retried_across_change` | violation | violation of NeverRetriedAcrossChange | 64 / 47 |
| `mutant_latest_only` | violation | violation of WorstCounts | 12 / 12 |
| `mutant_open_ignored` | violation | violation of WorstCounts | 11 / 11 |
| `mutant_flag_does_not_cap` | violation | violation of ShoppingIsCapped | 12 / 12 |
| `mutant_flag_missed` | violation | violation of ShoppingIsCapped | 12 / 12 |
| `mutant_cap_raises` | violation | violation of ShoppingIsCapped | 12 / 12 |
| `mutant_change_hides_history` | violation | violation of HistoryIsKept | 7 / 7 |

**`decisions`** (6 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 704 / 108 |
| `reach_flagged` | violation | violation of NeverFlagged | 9 / 9 |
| `mutant_identities_without_names` | violation | violation of FlagIsExact | 9 / 9 |
| `mutant_gone_is_not_flagged` | violation | violation of FlagIsExact | 9 / 9 |
| `mutant_refresh_on_edit` | violation | violation of FlagIsExact | 9 / 9 |
| `mutant_first_name_only` | violation | violation of FlagIsExact | 10 / 10 |

**`liveness`** (5 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 606 / 260 |
| `mutant_no_resubmit_after_unavailable` | temporal-violation | temporal violation | 570 / 260 |
| `mutant_no_resubmit_after_loss` | temporal-violation | temporal violation | 564 / 260 |
| `mutant_no_resubmit_after_error` | temporal-violation | temporal violation | 576 / 260 |
| `mutant_resubmits_unsupported` | temporal-violation | temporal violation | 651 / 260 |

### Run 9: every model, after the repairs of issue 27

2026-11-18. Job `e679b77f658b468f8f87a0e424144f5a` on the shared Oracle queue, sent from commit `6ec2b62` on branch `model-repairs` by `tools/check_models.py --batch --dumps` through the stage-0 host: every case of the nine models and the two state lists, 121 runs in one job, which completed and listed every case sent. 119 cases, every one matched. The executor measured the checker it ran: tla2tools.jar sha256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`, the upstream release 1.7.4. Every output and exit code is kept and hashed in [runs/index.json](runs/index.json), and the repository checks judge them again. Run from a development machine, not CI; CI repeats every case on each change to main. Outputs: [runs/run-9/](runs/run-9/).

**`kernel`** (14 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 27,385,032 / 3,575,936 |
| `design_three_hashes` | no-violation | no-violation | 1,660,815 / 202,428 |
| `design_flaky` | no-violation | no-violation | 315,212 / 38,704 |
| `reach_pass` | violation | violation of NeverPassed | 68 / 37 |
| `reach_fail` | violation | violation of NeverFailed | 88 / 47 |
| `reach_reuse` | violation | violation of NeverReusedAfterChange | 249 / 130 |
| `reach_conflict` | violation | violation of NeverConflict | 274 / 134 |
| `mutant_key_omits_tool` | violation | violation of Sound | 230 / 120 |
| `mutant_complete_with_current_key` | violation | violation of Sound | 223 / 117 |
| `mutant_complete_with_current_key_consistent` | violation | violation of Consistent | 2,904 / 1,190 |
| `mutant_unavailable_is_pass` | violation | violation of Provenance | 61 / 33 |
| `mutant_pass_outranks_fail` | violation | violation of NoPassOverFail | 274 / 134 |
| `assumption_undeclared_dep` | violation | violation of Sound | 266 / 140 |
| `assumption_flaky_provider` | violation | violation of Sound | 33 / 16 |

**`intent`** (18 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design_three_criteria` | no-violation | no-violation | 48,990,988 / 2,964,114 |
| `design_two_criteria` | no-violation | no-violation | 59,977,018 / 3,803,598 |
| `design_low_floor` | no-violation | no-violation | 76,469,914 / 4,032,666 |
| `floor_blocks_weak_grantor` | no-violation | no-violation | 34,565,536 / 2,224,908 |
| `reach_delivered` | violation | violation of NeverDelivered | 285 / 185 |
| `reach_fulfilled` | violation | violation of NeverFulfilled | 12,729 / 2,167 |
| `reach_delivered_by_amendment` | violation | violation of NeverDeliveredByAmendment | 393 / 265 |
| `mutant_worker_can_amend` | violation | violation of OnlyOwnerAmends | 59 / 39 |
| `mutant_worker_keeps_level` | violation | violation of WorkerIsSelf | 59 / 39 |
| `mutant_below_floor_counts` | violation | violation of FloorHolds | 55 / 35 |
| `mutant_missing_is_apart` | violation | violation of DefaultIsLowest | 79 / 59 |
| `mutant_hide_level` | violation | violation of LevelShown | 55 / 35 |
| `mutant_edit_keeps_confirmation` | violation | violation of GateProvenance | 51 / 35 |
| `mutant_draft_delivers` | violation | violation of DeliveredConfirmed | 2 / 2 |
| `mutant_unguarded_delivers` | violation | violation of DeliveredGuarded | 88 / 68 |
| `mutant_delivered_ignores_unknown` | violation | violation of DeliveredSound | 6 / 6 |
| `mutant_deferred_as_passed` | violation | violation of FulfilledSound | 15 / 13 |
| `mutant_declared_counts_in_full` | violation | violation of DeclaredIsCapped | 55 / 35 |

**`assurance`** (11 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 24,696 / 12,348 |
| `reach_proven` | violation | violation of NeverProven |  |
| `reach_shown` | violation | violation of NeverShown |  |
| `mutant_average` | violation | violation of WeakestLink |  |
| `mutant_ignore_unreported` | violation | violation of WeakestLink |  |
| `mutant_unknown_defect_counts` | violation | violation of NonVacuitySound |  |
| `mutant_empty_is_shown` | violation | violation of NonVacuitySound |  |
| `mutant_always_nothing` | violation | violation of WeakestLink |  |
| `mutant_fold_skips_middle` | violation | violation of WeakestLink |  |
| `mutant_observed_above_sampled` | violation | violation of WeakestLink |  |
| `mutant_failed_reported_none_planted` | violation | violation of NonVacuitySound |  |

**`attempts`** (19 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 6,648 / 6,648 |
| `design_claims_self` | no-violation | no-violation | 6,648 / 6,648 |
| `reach_agreed` | violation | violation of NeverAgreed | 5 / 5 |
| `reach_shopped` | violation | violation of NeverShopped | 12 / 12 |
| `reach_retried_across_change` | violation | violation of NeverRetriedAcrossChange | 72 / 72 |
| `reach_capped_by_limit` | violation | violation of NeverCappedByLimit | 108 / 108 |
| `mutant_latest_only` | violation | violation of WorstCounts | 12 / 12 |
| `mutant_open_ignored` | violation | violation of WorstCounts | 11 / 11 |
| `mutant_close_latest_open` | violation | violation of WorstCounts | 37 / 37 |
| `mutant_filed_at_close` | violation | violation of WorstCounts | 21 / 21 |
| `mutant_flag_does_not_cap` | violation | violation of RetryIsCapped | 12 / 12 |
| `mutant_flag_missed` | violation | violation of RetryIsCapped | 12 / 12 |
| `mutant_cap_on_shopping_only` | violation | violation of RetryIsCapped | 108 / 108 |
| `mutant_retried_only_on_same_target` | violation | violation of RetryIsCapped | 43 / 43 |
| `mutant_retried_hidden` | violation | violation of RetryIsCapped | 12 / 12 |
| `mutant_change_hides_history` | violation | violation of HistoryIsKept | 7 / 7 |
| `mutant_cap_raises` | violation | violation of RetryIsCapped | 12 / 12 |
| `mutant_cap_line_wide` | violation | violation of RetryIsCapped | 43 / 43 |
| `mutant_limit_off_by_one` | violation | violation of RetryIsCapped | 108 / 108 |

**`decisions`** (8 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 2,312 / 360 |
| `reach_flagged` | violation | violation of NeverFlagged | 9 / 9 |
| `mutant_identities_without_names` | violation | violation of FlagIsExact | 9 / 9 |
| `mutant_gone_is_not_flagged` | violation | violation of FlagIsExact | 9 / 9 |
| `mutant_refresh_on_edit` | violation | violation of FlagIsExact | 9 / 9 |
| `mutant_first_name_only` | violation | violation of FlagIsExact | 10 / 10 |
| `mutant_ungoverned_edit_flags` | violation | violation of FlagIsExact | 11 / 11 |
| `mutant_sticky_flag` | violation | violation of FlagIsExact | 59 / 59 |

**`liveness`** (5 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 606 / 260 |
| `mutant_no_resubmit_after_unavailable` | temporal-violation | temporal violation | 570 / 260 |
| `mutant_no_resubmit_after_loss` | temporal-violation | temporal violation | 564 / 260 |
| `mutant_no_resubmit_after_error` | temporal-violation | temporal violation | 576 / 260 |
| `mutant_resubmits_unsupported` | temporal-violation | temporal violation | 651 / 260 |

**`planner`** (13 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design_definition` | no-violation | no-violation | 82,796 / 38,166 |
| `design_file` | no-violation | no-violation | 98,745 / 48,725 |
| `file_costs_reruns` | violation | violation of NoNeedlessRerun | 86 / 59 |
| `reach_all_current` | violation | violation of NeverAllCurrent | 541 / 297 |
| `mutant_direct_deps_only` | violation | violation of NoWrongReuse | 87 / 59 |
| `mutant_no_deps` | violation | violation of NoWrongReuse | 85 / 58 |
| `mutant_closure_two_passes` | violation | violation of NoWrongReuse | 88 / 60 |
| `mutant_fallback_direct_deps_only` | violation | violation of NoWrongReuse | 87 / 60 |
| `mutant_key_omits_producer` | violation | violation of NoWrongReuse | 587 / 317 |
| `mutant_build_key_omits_compiler` | violation | violation of NoWrongReuse | 97 / 66 |
| `mutant_test_without_build` | violation | violation of NoWrongReuse | 551 / 304 |
| `mutant_plan_everything` | violation | violation of NoNeedlessRerun | 10 / 10 |
| `mutant_plan_nothing` | violation | violation of PlanComplete |  |

**`platforms`** (16 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design_stand_in_allowed` | no-violation | no-violation | 24,577 / 4,096 |
| `design_stand_in_forbidden` | no-violation | no-violation | 24,577 / 4,096 |
| `design_not_claimed` | no-violation | no-violation | 24,577 / 4,096 |
| `reach_stand_in` | violation | violation of NeverStoodIn | 15 / 15 |
| `reach_self_conflict` | violation | violation of NeverSelfConflict | 19 / 19 |
| `mutant_always_stand_in` | violation | violation of StatusMatches | 2 / 2 |
| `mutant_stand_in_unverified` | violation | violation of StatusMatches | 2 / 2 |
| `mutant_stand_in_unclaimed` | violation | violation of StatusMatches | 15 / 15 |
| `mutant_verified_globally` | violation | violation of StatusMatches | 146 / 80 |
| `mutant_stand_in_always_passed` | violation | violation of StatusMatches | 87 / 66 |
| `mutant_other_overrides_own` | violation | violation of StatusMatches | 21 / 21 |
| `mutant_self_disagreement_ignored` | violation | violation of StatusMatches | 19 / 19 |
| `mutant_latest_only_filed` | violation | violation of StatusMatches | 19 / 19 |
| `mutant_stand_in_not_reported` | violation | violation of StandInIsReported | 15 / 15 |
| `mutant_one_platform_reproduces` | violation | violation of ReproMatches | 2 / 2 |
| `mutant_disagreement_ignored` | violation | violation of ReproMatches | 19 / 19 |

**`tree`** (15 cases)

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 1,293,440 / 111,456 |
| `design_floor_two` | no-violation | no-violation | 1,293,440 / 111,456 |
| `reach_delivered` | violation | violation of NeverDelivered | 4,267 / 1,679 |
| `reach_delivered_floor_two` | violation | violation of NeverDelivered | 17,853 / 4,830 |
| `mutant_remove_keeps_confirmation` | violation | violation of ConfirmationMatches | 2,718 / 1,266 |
| `mutant_add_keeps_confirmation` | violation | violation of ConfirmationMatches | 556 / 408 |
| `mutant_edit_keeps_confirmation` | violation | violation of ConfirmationMatches | 554 / 406 |
| `mutant_unconfirmed_delivered` | violation | violation of DeliveryMatches | 81 / 81 |
| `mutant_delivered_ignores_child` | violation | violation of DeliveryMatches | 401 / 325 |
| `mutant_soft_child_is_delivered` | violation | violation of DeliveryMatches | 3,483 / 1,470 |
| `mutant_ignores_floor` | violation | violation of DeliveryMatches | 185 / 177 |
| `mutant_floor_applied_to_each_child` | violation | violation of DeliveryMatches | 17,853 / 4,830 |
| `mutant_floor_counts_root_only` | violation | violation of DeliveryMatches | 17,853 / 4,830 |
| `mutant_count_kept_on_remove` | violation | violation of DeliveryMatches | 4,347 / 1,794 |
| `mutant_count_misses_child_edit` | violation | violation of DeliveryMatches | 24,887 / 7,017 |

**Every state, both kernels.** The same day, on a development machine, `tools/check_states.py` compared both kernels as merged for issue 27, and again on 2026-11-19 as merged on branch kernel-host after they began to host providers (decision 0033), with the model on every state the two dump models of this job wrote out: 71,744 of the evidence model and 78,894 of the intent model, no differences for either kernel. The record, `run-9-kernel-on-every-state` in [runs/index.json](runs/index.json), hashes the comparisons' output and every source file of both kernels, so it stops counting when either kernel changes. Outputs: [runs/run-9/every-state/](runs/run-9/every-state/).

### Run 10: the repaired liveness model

2026-11-18. Job `acb93c9df63b43d7b29da7f4908c8d4e` on the shared Oracle queue, sent from branch `model-repairs` by `tools/check_models.py --batch --only liveness`: 7 cases in one job, which completed and listed every case sent; every one matched. The checker was measured as tla2tools 1.7.4. It replaces run 9 for this model, which ran before liveness gained `AnswerIsRight`. Outputs: [runs/run-10/](runs/run-10/).

| Case | Expected | Result | States generated / distinct |
|---|---|---|---|
| `design` | no-violation | no-violation | 1,026 / 430 |
| `reach_unsupported` | violation | violation of NeverUnsupported | 17 / 15 |
| `mutant_no_resubmit_after_unavailable` | temporal-violation | temporal violation | 954 / 430 |
| `mutant_no_resubmit_after_loss` | temporal-violation | temporal violation | 942 / 430 |
| `mutant_no_resubmit_after_error` | temporal-violation | temporal violation | 966 / 430 |
| `mutant_resubmits_unsupported` | temporal-violation | temporal violation | 1,071 / 430 |
| `mutant_gives_up_on_error` | violation | violation of AnswerIsRight | 32 / 28 |

### Run 11: both kernels on the retained model states

On 2026-11-21, both kernels at `9967ca9` agreed with the model on all 71,744 evidence states and all 78,894 intent states. The four comparisons used the retained state lists from completed model runs. Their model sources, settings and comparison tool matched the artifact's original inputs. Run 11 records the original model outputs, both kernel source identities and the new comparison results. [Comparison job](https://github.com/sloik/dodona/actions/runs/44899354441/job/136831864935) · [Recorded outputs](runs/run-11/every-state/).

### Run 12 — both kernels after preserving literal status names

On 2026-11-21, both kernels at `b0c0bbf` agreed with the model on all 71,744 evidence states and all 78,894 intent states per kernel. The hosted reviewer job compared the updated JavaScript status rules and both kernels against the same retained outputs used for Run 11. The models, settings and comparison tool matched the original completed shared-queue run. [Comparison job](https://github.com/sloik/dodona/actions/runs/44904165465/job/136846114856) · [Recorded outputs](runs/run-12/every-state/).

### Run 13 — both kernels after restoring a status mutation

On 2026-11-21, both kernels at `a5c9068` agreed with the model on all 71,744 evidence states and all 78,894 intent states per kernel. The comparison reused the completed state lists from Run 11. Its 107 input digests match the draft with the repaired mutation and anchor check. [Comparison job](https://github.com/sloik/dodona/actions/runs/44920837364/job/136896303543) · [Recorded outputs](runs/run-13/every-state/).

### Not a run: the first attempt at the rewritten models

A job with every case of the seven rewritten models was stopped by the queue part of the way, when the planner model outgrew the space a job is allowed. Thirty cases of four models had finished by then and each showed what it was expected to. They are not recorded as a run and no claim rests on them: a job that did not complete proves nothing here, whatever it left behind. The planner model has since been bounded by depth.
