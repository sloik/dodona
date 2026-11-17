# Formal models

Models of the kernel, written before any kernel exists. TLA+ is the initial binding ([decision 0013](../decisions/0013-initial-binding-for-kernel-models.md)).

| Model | Covers |
|---|---|
| [kernel/EvidenceReuse.tla](kernel/EvidenceReuse.tla) | When a recorded result may be reused, under edits, tool changes, lost runs, results arriving after an edit, and a provider that can be wrong |
| [intent/IntentGates.tla](intent/IntentGates.tla) | When an intent may be reported delivered or fulfilled, and that a gate changes only through an owner's recorded amendment, with self-granted ones always marked and blocked where an independent approver is required |

## Running a model

Each model directory has an `expected.json` listing every configuration, the outcome it must produce, and why. A model counts as checked only when **every** case matches: the design configurations find no violation, every planted defect is caught by the named property, and every reachability case is reached. The exit code decides: a run that ends any other way counts as neither outcome. A design run on its own proves little, because a property that cannot fail also passes.

`tools/check_models.py` runs every case through an executor you name in a site file and judges the results; `--replay` judges outputs you already have. It never starts the model checker itself. Where the model checker runs is a site choice ([decision 0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md)): run the pinned tool with the listed arguments through whatever executor your site uses. A run that did not finish is not a pass.

## Claims

[CLAIMS.md](CLAIMS.md) maps each architecture claim to the check behind it and records whether that check has actually run.
