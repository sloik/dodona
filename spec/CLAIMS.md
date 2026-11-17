# Architecture claims

Each claim the architecture makes, the check that could show it false, and whether that check has run.

Status values:

- **checked**: every case of the check ran to completion with the expected outcome, including its planted defects. The run is referenced.
- **modelled, unchecked**: a model exists; no completed run is recorded.
- **not yet modelled**: the claim is only prose so far.

A bounded model check shows the property for the bounds in the configuration, not for all sizes. None of these results says anything about an implementation; that is a separate conformance obligation ([decision 0012](../decisions/0012-spec-to-code-conformance-is-an-explicit-seam.md)).

| # | Claim | Decision | Check | Planted defect that must fail | Status |
|---|---|---|---|---|---|
| C1 | A reported pass is true for the current inputs, and a reported failure is false for them, under any interleaving of edits, tool changes, outages, lost runs and completions | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Sound` in `kernel/EvidenceReuse.tla` | Key leaves out the tool digest; result filed under the key at completion | STATUS_C1 |
| C2 | An unreachable backend never produces a pass | [0005](../decisions/0005-closed-verdict-set.md) | `Sound`, same model | Unavailable recorded as passed | STATUS_C1 |
| C3 | Reuse is unsound if a provider under-declares dependencies, so that assumption belongs in the trusted base | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Sound` fails with `undeclared_dep` | (the defect is the check) | STATUS_C1 |
| C4 | No evidence key ever holds both a pass and a failure | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | `Consistent`, same model | None yet, so this check has not been shown able to fail | STATUS_C4 |
| C5 | The same content has the same identity on every platform | [0004](../decisions/0004-definition-identity-comes-from-the-language-provider.md), [0009](../decisions/0009-platform-order-and-portability-rules.md) | Conformance: hashing vectors run on each platform | A vector with a case-only path collision; one with mixed line endings | not yet modelled |
| C6 | File-level fallback identity can cause extra reruns but never a wrong reuse | [0004](../decisions/0004-definition-identity-comes-from-the-language-provider.md) | Model: refinement of C1 with coarser keys | Fallback that ignores a declared dependency | not yet modelled |
| C7 | The planner reruns every stale obligation and no obligation that is not stale | [0006](../decisions/0006-evidence-key-and-trusted-base.md) | Model, plus conformance scenarios | Planner that skips a transitive dependent | not yet modelled |
| C8 | A check never runs on an executor the configuration did not name | [0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md) | Model, plus conformance scenario with the executor down | Kernel with a silent local fallback | not yet modelled |
| C9 | No malformed or out-of-order provider message leads to a pass | [0003](../decisions/0003-providers-are-separate-processes.md) | Conformance: malformed-message cases | Kernel that defaults a missing verdict to passed | not yet modelled |
| C10 | Adding a platform to the lock changes no existing entry | [0008](../decisions/0008-reproducibility-levels.md) | Conformance: resolve on one platform, then add a second | Resolver that reorders or re-resolves existing entries | not yet modelled |
| C11 | Two platforms disagreeing at the chosen reproducibility level is reported as a failure | [0008](../decisions/0008-reproducibility-levels.md) | Conformance scenario with divergent records | Kernel that compares only the latest record | not yet modelled |
| C12 | A decision is flagged when a definition it governs changes | [0001](../decisions/0001-decisions-are-nodes.md) | Model, plus conformance scenario | Index that resolves `governs` by path only | not yet modelled |
| C13 | Two kernels that pass the conformance kit agree on every kit scenario | [0011](../decisions/0011-self-hosting-through-a-verified-seed.md) | Differential run of both kernels | A kernel carrying one modelled defect | not yet modelled |
| C14 | If the backend is eventually reachable, every obligation eventually gets a reusable verdict or a stated reason why not | [0005](../decisions/0005-closed-verdict-set.md) | Liveness property; needs fairness assumptions | Planner that never resubmits after `unavailable` | not yet modelled |

## Assumptions the models make

These are not proven; they are the trusted base, and each needs its own check or an explicit decision to trust it.

- A completed run judges exactly the input snapshot taken at submission. The snapshot must really be immutable.
- A provider's verdict is correct for the inputs it was given.
- Equal hashes mean equal content.
- The ledger is append-only and its records are not altered after writing.
