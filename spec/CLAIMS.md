# Architecture claims

Each claim the architecture makes, the check that could show it false, and whether that check has run.

Status values:

- **checked**: every case of the check ran to completion with the expected outcome, including its planted defects. The run is listed under [Recorded runs](#recorded-runs).
- **modelled, unchecked**: a model exists; no completed run is recorded.
- **not yet modelled**: the claim is only prose so far.

What a `checked` status means here, and no more:

- A bounded model check shows a property for the bounds in the configuration, not for all sizes. The bounds are two definitions, two obligations, two hash values and at most two runs in flight, with a smaller instance where noted.
- The model has one kernel, a ledger that keeps what it is given, abstract hashes that never collide, and fixed dependency sets.
- Nothing here says anything about an implementation. That is a separate conformance obligation ([decision 0012](../decisions/0012-spec-to-code-conformance-is-an-explicit-seam.md)).

## Modelled in `kernel/EvidenceReuse.tla`

| # | Claim | Decision | Property | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C1 | Given a provider that is correct and declares all its inputs: a reported pass means the obligation holds for the current inputs, and a reported failure means it does not, under any interleaving of edits, tool changes, lost runs and completions | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Sound` | Key leaves out the tool digest; result filed under the key at completion | modelled, unchecked |
| C2 | Every reusable record was produced by a run that completed; an unreachable backend never produces one | [0005](../decisions/0005-closed-verdict-set.md) | `Provenance` | Unavailable recorded as passed | modelled, unchecked |
| C3 | With a correct provider, no evidence key ever holds both a pass and a failure | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Consistent` | Result filed under the key at completion | modelled, unchecked |
| C4 | Even with a provider that can be wrong, a pass is never reported while a failure is recorded for the same key | [0005](../decisions/0005-closed-verdict-set.md) | `NoPassOverFail`, small instance | With conflicting records, the pass wins | modelled, unchecked |
| C5 | The design does reuse records after a change that does not affect them, so C1 is not satisfied by rerunning everything | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | Reachability: `NeverReusedAfterChange` must be violated | (reachability) | modelled, unchecked |
| C6 | C1 depends on two trusted-base assumptions: complete declared inputs, and a correct provider. Removing either breaks it | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Sound` must be violated in both cases | (the broken assumption is the check) | modelled, unchecked |

C6 does not show the assumptions hold. It shows they are load-bearing, which is why they are in the [trusted base](../MODEL.md#6-trusted-base).

## Not yet modelled

| # | Claim | Decision | Intended check | Planted defect that must fail |
|---|---|---|---|---|
| C7 | The same content has the same identity on every platform, and a path is accepted on all platforms or none | [0004](../decisions/0004-definition-identity-comes-from-the-language-provider.md), [0009](../decisions/0009-platform-order-and-portability-rules.md) | Conformance vectors for the encoding and the path check | A checker that folds case with the platform's own rules |
| C8 | File-level fallback identity can cause extra reruns but never a wrong reuse | [0004](../decisions/0004-definition-identity-comes-from-the-language-provider.md) | Model: C1 with coarser keys | Fallback that ignores a declared dependency |
| C9 | The planner reruns every stale obligation and no obligation that is not stale, including when dependency sets change | [0002](../decisions/0002-small-kernel-everything-else-is-a-provider.md) | Model with changing dependencies, plus scenarios | Planner that skips a transitive dependent |
| C10 | Changing a build tool invalidates checks of what it built | [0012](../decisions/0012-spec-to-code-conformance-is-an-explicit-seam.md) | Model with artifact nodes | Key that omits the producing obligation |
| C11 | A check never runs on an executor the configuration did not name, and a mismatch between requested and reported tools or platform is never a result | [0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md) | Model, plus scenarios with the executor down and with a lying executor | Kernel with a silent local fallback |
| C12 | A run is not submitted twice and not lost across a kernel restart | [0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md) | Model with handles and restart | Kernel that resubmits on restart |
| C13 | No malformed, late or out-of-order provider message leads to a pass | [0003](../decisions/0003-providers-are-separate-processes.md) | The misbehaving test provider | Kernel that defaults a missing verdict to passed |
| C14 | Adding a platform to the lock changes no existing entry | [0008](../decisions/0008-reproducibility-levels.md) | Scenario: resolve on one platform, add a second | Resolver that re-resolves existing entries |
| C15 | Two platforms disagreeing at the chosen level is reported as a failure, and one platform alone is reported as unknown | [0008](../decisions/0008-reproducibility-levels.md) | Model with the platform in the key | Kernel that reuses one platform's record for another |
| C16 | A decision is flagged when the identity behind a name it governs changes, in content-addressed languages too | [0001](../decisions/0001-decisions-are-nodes.md) | Model, plus scenario | Index that tracks identities without names |
| C17 | A change that weakens policy is always visible in the report | [0014](../decisions/0014-policy-is-separate-from-configuration.md) | Scenarios: lowered bound, removed obligation, weaker provider | Kernel that judges against the edited policy only |
| C18 | A record no trusted kernel wrote is never reused; a torn ledger write never changes a status silently | [0015](../decisions/0015-ledger-integrity-and-record-trust.md) | Model with two writers and crash points, plus scenarios | Kernel that accepts any record with a valid hash |
| C19 | An obligation is reported non-vacuous only when every planted defect of it was caught | [data model](../MODEL.md#3-obligations) | Model, plus scenario | Kernel that ignores a planted defect that did not run |
| C20 | The conformance kit rejects kernels with known defects | [0011](../decisions/0011-self-hosting-through-a-verified-seed.md) | Run defective kernels against the kit; report the fraction rejected | A kit with a scenario removed |
| C21 | Two independent kernels agree on real project states, and any disagreement is reported as a conflict | [0011](../decisions/0011-self-hosting-through-a-verified-seed.md) | Differential runs beyond the kit | A kernel carrying a defect the kit does not target |
| C22 | If the backend is eventually reachable, every obligation eventually gets a reusable verdict or a stated reason why not | [0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md) | Liveness property, with fairness assumptions | Planner that never resubmits after `unavailable` |
| C23 | An intent is never reported delivered with a hard gate not passed, nor fulfilled with a deferred gate open | [0018](../decisions/0018-hard-soft-and-deferred-gates.md) | Model of intent status, plus scenarios | Kernel that treats a deferred gate as passed |
| C24 | A criterion's reported assurance is never above its weakest link | [0019](../decisions/0019-assurance-is-stated-per-link.md) | Model, plus scenarios | Kernel that averages the links |
| C25 | No gate is passed, moved or dropped without an amendment on record, and a self-granted amendment is always shown, and never counts where an independent approver is required | [0020](../decisions/0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md) | Model with owner and worker identities, plus scenarios | Kernel that accepts an amendment from the worker as the owner's |
| C26 | A varying check is never reported from fewer runs than it declared | [0018](../decisions/0018-hard-soft-and-deferred-gates.md) | Scenarios with declared sample sizes | Kernel that stops at the first passing run |
| C27 | Two intents that touch the same definition are reported as colliding before work starts | [0017](../decisions/0017-intent-in-plain-words-broken-down.md) | Scenarios | Index that compares declared paths only as text |

## Recorded runs

None yet. The model checks have been submitted and have not finished.
