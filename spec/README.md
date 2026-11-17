# Formal models

Models of the kernel, written before any kernel exists. TLA+ is the initial binding ([decision 0013](../decisions/0013-initial-binding-for-kernel-models.md)).

| Model | Covers |
|---|---|
| [kernel/EvidenceReuse.tla](kernel/EvidenceReuse.tla) | When a recorded result may be reused, under edits, tool changes, lost runs, results arriving after an edit, and a provider that can be wrong |
| [intent/IntentGates.tla](intent/IntentGates.tla) | When an intent may be reported delivered or fulfilled, and that a gate changes only through an owner's recorded amendment, with self-granted ones always marked and blocked where an independent approver is required |
| [planner/Planner.tla](planner/Planner.tla) | What is rerun after a change: indirect dependencies, build tools, and file-level identity as a fallback |
| [assurance/Assurance.tla](assurance/Assurance.tla) | The shown level as the weakest link, and when a check counts as shown able to fail |
| [tree/IntentTree.tla](tree/IntentTree.tla) | A parent intent and its children |
| [attempts/Attempts.tla](attempts/Attempts.tla) | Trying a judgement again until it agrees |
| [platforms/Platforms.tla](platforms/Platforms.tla) | Results on more than one platform, and when one may stand in for another |
| [decisions/Decisions.tla](decisions/Decisions.tla) | A decision flagged when what it governs changes |
| [liveness/Liveness.tla](liveness/Liveness.tla) | Every obligation is eventually decided, under stated assumptions |

## Checking the kernel against the models

`kernel/MCDump.tla` and `intent/MCDump.tla` are the same models with one more variable holding the model's own answer in each state. The model checker writes out every state it reaches, and `tools/check_states.py` requires the kernel to give that answer for every one. That ties the code to the model for all states within the model's bounds, not a sample.

## Running a model

Each model directory has an `expected.json` listing every configuration, the outcome it must produce, and why. A model counts as checked only when **every** case matches: the design configurations find no violation, every planted defect is caught by the named property, and every reachability case is reached. The exit code decides: a run that ends any other way counts as neither outcome. A design run on its own proves little, because a property that cannot fail also passes.

`tools/check_models.py` runs every case through an executor you name in a site file and judges the results; `--replay` judges outputs you already have. It never starts the model checker itself. Where the model checker runs is a site choice ([decision 0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md)): run the pinned tool with the listed arguments through whatever executor your site uses. A run that did not finish is not a pass.

## Claims

[CLAIMS.md](CLAIMS.md) maps each architecture claim to the check behind it and records whether that check has actually run.
