---
id: "0005"
title: A kernel can be judged by something that is not a kernel
owner: project owner
worker: the agents building dodona
parent: "0001"
touches:
  - conformance/
criteria: [{"id": "1", "words": "Every modelled defect has a scenario that a kernel repeating it fails", "gate": "hard", "checked_by": "The repository check gap every modelled case has a scenario, and tools/kit adequacy.py"}, {"id": "2", "words": "A deliberately misbehaving provider exists and every case ends in error", "gate": "hard", "checked_by": "tools/run provider cases.py and tools/run check cases.py, against two stage-0 hosts; no kernel hosts a provider yet. Not an obligation a kernel can read yet"}, {"id": "3", "words": "Kernels with known defects are rejected by the kit, and the fraction is reported", "gate": "hard", "checked_by": "tools/kit adequacy.py, run on every change. Not an obligation a kernel can read yet"}]
---

# 0005. A kernel can be judged by something that is not a kernel

Before any kernel exists, there is a body of scenarios that says what a correct one must do, written without reference to any implementation.

## Criteria

<!-- criteria: written by tools/intents.py from the front matter; do not edit -->
| # | Criterion | Gate | Checked by | Observed after delivery |
|---|---|---|---|---|
| 1 | Every modelled defect has a scenario that a kernel repeating it fails | hard | nothing a kernel reads yet. The repository check gap every modelled case has a scenario, and tools/kit adequacy.py |  |
| 2 | A deliberately misbehaving provider exists and every case ends in error | hard | nothing a kernel reads yet. tools/run provider cases.py and tools/run check cases.py, against two stage-0 hosts; no kernel hosts a provider yet. Not an obligation a kernel can read yet |  |
| 3 | Kernels with known defects are rejected by the kit, and the fraction is reported | hard | nothing a kernel reads yet. tools/kit adequacy.py, run on every change. Not an obligation a kernel can read yet |  |
<!-- end of criteria -->
