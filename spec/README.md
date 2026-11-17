# Formal models

Models of the kernel, written before any kernel exists. TLA+ is the initial binding ([decision 0013](../decisions/0013-initial-binding-for-kernel-models.md)).

| Model | Covers |
|---|---|
| [kernel/EvidenceReuse.tla](kernel/EvidenceReuse.tla) | When a recorded result may be reused, under edits, tool changes, outages, lost runs and results arriving after an edit |

## Running a model

Each model directory has an `expected.json` listing every configuration, the outcome it must produce, and why. A model counts as checked only when **every** case matches: the design configuration finds no violation, and every planted defect is caught by the named property. A design run on its own proves little, because a property that cannot fail also passes.

dodona does not ship a launcher. Where the model checker runs is a site choice ([decision 0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md)): run the pinned tool with the listed arguments through whatever executor your site uses. A run that did not finish is not a pass.

## Claims

[CLAIMS.md](CLAIMS.md) maps each architecture claim to the check behind it and records whether that check has actually run.
