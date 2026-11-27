# Formal models

On 17 November 2026, the evidence model's [Run 2](https://github.com/sloik/dodona/commit/37b82ec4f823176252c63b8745e20d62df3324d4) completed the design case left unfinished by Run 1. The intent model's [Run 3](https://github.com/sloik/dodona/commit/ef34657292b4de665694283a7c7ccab2fcadb0ad) recorded 13 matching cases. Both records precede [the first seed-kernel commit](https://github.com/sloik/dodona/commit/682041f0aeae9e0d87c4bbeb6ac9cde7ad0bf0c8). [Seven more models followed later that day](https://github.com/sloik/dodona/commit/13e928c7c6c8c7a540e0650b42ce6265950f3f5b). TLA+ is the initial binding ([decision 0013](../decisions/0013-initial-binding-for-kernel-models.md)).

| Model | Covers |
|---|---|
| [kernel/EvidenceReuse.tla](kernel/EvidenceReuse.tla) | When a recorded result may be reused, under edits, tool changes, lost runs, results arriving after an edit, and a provider that can be wrong |
| [intent/IntentGates.tla](intent/IntentGates.tla) | When an intent may be reported delivered or fulfilled, and that a gate changes only through an owner's recorded amendment, with self-granted ones always marked and blocked where an independent approver is required |
| [planner/Planner.tla](planner/Planner.tla) | What is rerun after a change and which artifact a test consumes |
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

The model-checker provider lists the input files of each obligation. The provider and runner identities form part of its evidence key, so changing either requires fresh results before those obligations can be reused. [Decision 0034](../decisions/0034-a-kernel-runs-a-project-and-reports-its-status.md) describes the move from the helper to the kernel.

The model workflow runs the project's obligations through the first kernel. The second kernel reads the resulting ledger under the same protected policy. The workflow requires agreement between those reports and a current passing result for every case in the model inventory. Newly run cases also need matching commands, inputs, captured output and expected outcomes. The separate dump plan keeps its own keys, tool measurements and completion checks. Both kernels continue to be compared against every state in the two dumps before the workflow keeps the ledger for the next run.

## Claims

[CLAIMS.md](CLAIMS.md) maps each architecture claim to the check behind it and records whether that check has actually run.
