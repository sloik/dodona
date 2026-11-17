---
id: "0005"
title: A kernel can be judged by something that is not a kernel
owner: project owner
parent: "0001"
touches:
  - conformance/
---

# 0005. A kernel can be judged by something that is not a kernel

Before any kernel exists, there is a body of scenarios that says what a correct one must do, written without reference to any implementation.

## Criteria

| # | Criterion | Gate | Checked by |
|---|---|---|---|
| 1 | Every modelled defect has a scenario that a kernel repeating it fails | hard | The repository check `gap_every_modelled_case_has_a_scenario`, and `tools/kit_adequacy.py` |
| 2 | A deliberately misbehaving provider exists and every case ends in error | hard | Not yet covered |
| 3 | Kernels with known defects are rejected by the kit, and the fraction is reported | hard | `tools/kit_adequacy.py`, run on every change: 15 of 15 |
