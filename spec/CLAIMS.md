# Architecture claims

Each claim the architecture makes, the check that could show it false, and whether that check has run.

Status values:

- **checked**: every case of the check ran to completion with the expected outcome, including its planted defects, against the model files as they are now. The run is listed under [Recorded runs](#recorded-runs) and in [runs/index.json](runs/index.json); the repository checks fail if a claim is marked checked and its model files have changed since.
- **modelled, unchecked**: a model exists; no completed run is recorded.
- **not yet modelled**: the claim is only prose so far.

What a `checked` status means here, and no more:

- A bounded model check shows a property for the bounds in the configuration, not for all sizes. The bounds are two definitions, two obligations, two hash values and at most two runs in flight, with a smaller instance where noted.
- The model has one kernel, a ledger that keeps what it is given, abstract hashes that never collide, and fixed dependency sets.
- Nothing here says anything about an implementation. That is a separate conformance obligation ([decision 0012](../decisions/0012-spec-to-code-conformance-is-an-explicit-seam.md)).

## Modelled in `kernel/EvidenceReuse.tla`

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C1 | Given a provider that is correct and declares all its inputs: a reported pass means the obligation holds for the current inputs, and a reported failure means it does not, under any interleaving of edits, tool changes, lost runs and completions | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Sound` | Key leaves out the tool digest; result filed under the key at completion | **checked**, runs 1 and 5 |
| C2 | Every reusable record was produced by a run that completed; an unreachable backend never produces one | [0005](../decisions/0005-closed-verdict-set.md) | `Provenance` | Unavailable recorded as passed | **checked**, runs 1 and 5 |
| C3 | With a correct provider, no evidence key ever holds both a pass and a failure | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Consistent` | Result filed under the key at completion | **checked**, runs 1 and 5 |
| C4 | Even with a provider that can be wrong, a pass is never reported while a failure is recorded for the same key | [0005](../decisions/0005-closed-verdict-set.md) | `NoPassOverFail`, small instance | With conflicting records, the pass wins | **checked**, run 1 |
| C5 | The design does reuse records after a change that does not affect them, so C1 is not satisfied by rerunning everything | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | Reachability: `NeverReusedAfterChange` must be violated | (reachability) | **checked**, run 1 |
| C6 | C1 depends on two trusted-base assumptions: complete declared inputs, and a correct provider. Removing either breaks it | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Sound` must be violated in both cases | (the broken assumption is the check) | **checked**, run 1 |

C6 does not show the assumptions hold. It shows they are load-bearing, which is why they are in the [trusted base](../MODEL.md#6-trusted-base).

## Modelled in `intent/IntentGates.tla`

Bounds: one intent with two or three criteria (hard and deferred), at most one or two amendments, three separation levels.

This model is narrow. It takes a recorded separation level as given and checks only what the kernel does with it; whether the level is true is outside it. `DeliveredSound`, `DeliveredConfirmed`, `DeliveredGuarded` and `FulfilledSound` can only catch a kernel that computes the report wrongly. `GateProvenance` does not require the amendment to come before the change. Not covered: child intents, the text of criteria, assurance levels, time limits and checks that vary between runs.

The model was rewritten on 2026-11-17 to add the baseline, the unguarded rule and graded separation. Runs 3 and 4 were of earlier versions and support no current claim. The model was changed again so that a level which is only declared counts as `helper` at most; it has not been run since.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C23 | An intent is never reported delivered with a hard gate not passed, nor fulfilled with a deferred gate open | [0018](../decisions/0018-hard-soft-and-deferred-gates.md) | `DeliveredSound`, `FulfilledSound` | A hard gate whose check has not run is treated as passed; an open deferred gate does not block fulfilment | modelled, unchecked |
| C25 | While an intent is confirmed, a gate differs from the baseline only through an amendment on record that took effect, and only the owner's amendments take effect | [0020](../decisions/0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md) | `GateProvenance`, `OnlyOwnerAmends` | A gate is edited and the intent stays confirmed; the worker's amendment takes effect | modelled, unchecked |
| C28 | Amendments are live rules: a sufficiently separate owner's amendment can open the way to delivery, and one below the floor cannot | [0020](../decisions/0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md) | Reachability of delivery by amendment, and its absence when the grantor cannot reach the floor | (reachability) | modelled, unchecked |
| C29 | An intent the owner has not confirmed, or that was edited since, is never reported delivered | [0017](../decisions/0017-intent-in-plain-words-broken-down.md) | `DeliveredConfirmed` | An unconfirmed intent is reported delivered | modelled, unchecked |
| C30 | An intent with fewer hard gates than policy demands is never reported delivered. Children are not modelled | [0018](../decisions/0018-hard-soft-and-deferred-gates.md) | `DeliveredGuarded` | An intent with no hard gate is reported delivered | modelled, unchecked |
| C33 | An act with no separation recorded is graded `self`, as is the worker granting to itself; an amendment below policy's floor does not take effect; the level reported is the level used | [0024](../decisions/0024-separation-is-graded-not-enforced.md) | `DefaultIsLowest`, `WorkerIsSelf`, `FloorHolds`, `LevelShown` | Nothing recorded treated as a high level; the worker keeps the level it wrote down; an amendment below the floor takes effect; a higher level shown than recorded | modelled, unchecked |

## Modelled in `planner/Planner.tla`

Bounds: three definitions (one depending on another, one unrelated in the same file), two hash values, a compiler and a test runner, at most three records. Dependency sets do not change.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C9 | Nothing stale is reused, including what is stale through an indirect dependency, and with per-definition identity nothing current is rerun | [0002](../decisions/0002-small-kernel-everything-else-is-a-provider.md) | `NoWrongReuse`, `NoNeedlessRerun` | The key covers the target and not what it depends on; the planner reruns everything | modelled, unchecked |
| C8 | File-level fallback identity never causes a wrong reuse. It does cause extra reruns, and that is shown too | [0004](../decisions/0004-definition-identity-comes-from-the-language-provider.md) | `NoWrongReuse` with file identity; `NoNeedlessRerun` must be violated there | The fallback ignores a dependency | modelled, unchecked |
| C10 | Changing a build tool makes checks of what it built stale | [0012](../decisions/0012-spec-to-code-conformance-is-an-explicit-seam.md) | `NoWrongReuse` | A test's key leaves out the build that produced what it tests | modelled, unchecked |

## Modelled in `assurance/Assurance.tla`

Every combination of three links, each with one of six levels or unreported, and two planted defects, each passed, failed, unknown or absent. This is the whole input space of the rule, not a sample of it.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C24 | A criterion's shown level is the weakest of its evidence links: never above any link, and never lower than it has to be | [0019](../decisions/0019-assurance-is-stated-per-link.md) | `WeakestLink`, `NotUnderstated` | The links are averaged; the level is always the lowest | modelled, unchecked |
| C31 | An evidence link with nothing reported counts as none and never raises the level | [0019](../decisions/0019-assurance-is-stated-per-link.md) | `WeakestLink` | A link nobody reported is left out | modelled, unchecked |
| C19 | A check is reported as shown able to fail only when it has planted defects and every one was caught | [data model](../MODEL.md#3-obligations) | `NonVacuitySound` | A planted defect that never ran counts as caught; a check with none planted is reported as shown | modelled, unchecked |

## Modelled in `tree/IntentTree.tla`

Bounds: a root with up to two children, one criterion each, hard or soft. One level of children; no exceptions.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C34 | A parent is delivered only when every child is; a child with no hard gate never is; and adding or removing a child, or editing any gate, needs the owner's confirmation again | [0017](../decisions/0017-intent-in-plain-words-broken-down.md) | `TreeSound`, `ShapeIsConfirmed` | A child is removed or added and the root stays confirmed; the root is delivered whatever its children are; a child made soft counts as delivered | modelled, unchecked |

## Modelled in `attempts/Attempts.tla`

Bounds: at most three attempts and one change of target. Attempts made without taking a ticket leave no record and are outside the model.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C35 | On an unchanged target the worst result counts and an attempt left open counts as a failure; an agreement after an attempt that did not agree is flagged, and the flag caps the separation of the act | [0024](../decisions/0024-separation-is-graded-not-enforced.md) | `WorstCounts`, `ShoppingIsFlagged` | Only the latest attempt counts; an open attempt is ignored; shopping is not flagged; the flag does not cap | modelled, unchecked |

## Modelled in `platforms/Platforms.tla`

Bounds: two sets of inputs and two platforms.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C15 | A status rests on another platform's record only when policy allows it and the claim of platform independence is verified; reproducibility passes only with two agreeing platforms and fails on any disagreement | [0008](../decisions/0008-reproducibility-levels.md) | `StandInIsEarned`, `ReproSound` | A record always stands in; a record stands in unverified; one platform alone is reported as reproduced; a disagreement is not a failure | modelled, unchecked |

## Modelled in `decisions/Decisions.tla`

Bounds: two names, two contents and absence.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C16 | A decision is flagged exactly when the content behind the name it governs is no longer the content it recorded, including when the name disappears, and whether or not the old content exists elsewhere | [0001](../decisions/0001-decisions-are-nodes.md) | `FlagIsExact` | The kernel tracks contents without names; a name that disappears is not flagged | modelled, unchecked |

## Modelled in `liveness/Liveness.tla`

Bounds: one obligation; at most two edits, two outages and two lost runs. The claim holds only under the stated assumptions: the kernel keeps submitting what is undecided, the backend comes back, and a run in flight finishes unless it is lost. No scenario in the conformance kit covers this, because the seed kernel has no loop that submits work.

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C22 | Under those assumptions, every obligation is eventually decided and stays decided | [0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md) | `EventuallyDecided` | After finding the backend down, or after a lost run, the kernel never tries again | modelled, unchecked |

## Not yet modelled

| # | Claim | Decision | Intended check | Planted defect that must fail |
|---|---|---|---|---|
| C7 | The same content has the same identity on every platform, and a path is accepted on all platforms or none | [0004](../decisions/0004-definition-identity-comes-from-the-language-provider.md), [0009](../decisions/0009-platform-order-and-portability-rules.md) | Conformance vectors for the encoding and the path check | A checker that folds case with the platform's own rules |
| C11 | A check never runs on an executor the configuration did not name, and a mismatch between requested and reported tools or platform is never a result | [0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md) | Model, plus scenarios with the executor down and with a lying executor | Kernel with a silent local fallback |
| C12 | A run is not submitted twice and not lost across a kernel restart | [0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md) | Model with handles and restart | Kernel that resubmits on restart |
| C13 | No malformed, late or out-of-order provider message leads to a pass | [0003](../decisions/0003-providers-are-separate-processes.md) | The misbehaving test provider | Kernel that defaults a missing verdict to passed |
| C14 | Adding a platform to the lock changes no existing entry | [0008](../decisions/0008-reproducibility-levels.md) | Scenario: resolve on one platform, add a second | Resolver that re-resolves existing entries |
| C17 | A change that weakens policy is always visible in the report | [0014](../decisions/0014-policy-is-separate-from-configuration.md) | Scenarios: lowered bound, removed obligation, weaker provider | Kernel that judges against the edited policy only |
| C18 | A record no trusted kernel wrote is never reused; a torn ledger write never changes a status silently | [0015](../decisions/0015-ledger-integrity-and-record-trust.md) | Model with two writers and crash points, plus scenarios | Kernel that accepts any record with a valid hash |
| C20 | The conformance kit rejects kernels with known defects. Measured, not modelled: `tools/kit_adequacy.py` plants 15 defects in the seed kernel and the kit rejects 15 | [0011](../decisions/0011-self-hosting-through-a-verified-seed.md) | Run defective kernels against the kit; report the fraction rejected | A kit with a scenario removed |
| C21 | Two independent kernels agree on real project states, and any disagreement is reported as a conflict | [0011](../decisions/0011-self-hosting-through-a-verified-seed.md) | Differential runs beyond the kit | A kernel carrying a defect the kit does not target |
| C26 | A varying check is never reported from fewer runs than it declared | [0018](../decisions/0018-hard-soft-and-deferred-gates.md) | Scenarios with declared sample sizes | Kernel that stops at the first passing run |
| C27 | Two intents that touch the same definition are reported as colliding before work starts | [0017](../decisions/0017-intent-in-plain-words-broken-down.md) | Scenarios | Index that compares declared paths only as text |
| C32 | A status is never shown without its headline, and a self-granted exception or unverified independence is always in it | [0019](../decisions/0019-assurance-is-stated-per-link.md), [0020](../decisions/0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md) | Scenarios on the agent interface | Interface that returns the status word alone |
| C36 | A separation level is never shown without its weakest source, and a fact not covered by a valid attestation is treated as declared | [0024](../decisions/0024-separation-is-graded-not-enforced.md) | Scenarios | Kernel that trusts an unsigned attestation |

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
