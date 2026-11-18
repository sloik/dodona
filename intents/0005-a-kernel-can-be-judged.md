---
id: "0005"
title: A kernel can be judged by something that is not a kernel
owner: project owner
worker: the agents building dodona
parent: "0001"
touches:
  - conformance/
criteria: [{"id": "1", "words": "Every modelled defect has a scenario that a kernel repeating it fails", "gate": "hard", "checked_by": "The repository check `gap_every_modelled_case_has_a_scenario`, and `tools/kit_adequacy.py`"}, {"id": "2", "words": "A deliberately misbehaving provider exists and every case ends in error", "gate": "hard", "checked_by": "`tools/run_provider_cases.py` and `tools/run_check_cases.py`, against two stage-0 hosts; no kernel hosts a provider yet. Not an obligation a kernel can read yet"}, {"id": "3", "words": "Kernels with known defects are rejected by the kit, and the fraction is reported", "gate": "hard", "checked_by": "`tools/kit_adequacy.py`, run on every change. Not an obligation a kernel can read yet"}]
---

# 0005. A kernel can be judged by something that is not a kernel

Before any kernel exists, there is a body of scenarios that says what a correct one must do, written without reference to any implementation.

## Criteria

<!-- criteria: written by tools/intents.py from the front matter; do not edit -->
| # | Criterion | Gate | Checked by |
|---|---|---|---|
| 1 | Every modelled defect has a scenario that a kernel repeating it fails | hard | The repository check `gap_every_modelled_case_has_a_scenario`, and `tools/kit_adequacy.py` |
| 2 | A deliberately misbehaving provider exists and every case ends in error | hard | `tools/run_provider_cases.py` and `tools/run_check_cases.py`, against two stage-0 hosts; no kernel hosts a provider yet. Not an obligation a kernel can read yet |
| 3 | Kernels with known defects are rejected by the kit, and the fraction is reported | hard | `tools/kit_adequacy.py`, run on every change. Not an obligation a kernel can read yet |
<!-- end of criteria -->
