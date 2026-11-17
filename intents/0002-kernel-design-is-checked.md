---
id: "0002"
title: The kernel's rules are checked before any kernel is written
owner: project owner
parent: "0001"
checks: {"2": ["*/mutant_*", "*/assumption_*"], "3": ["*/design*"]}
touches:
  - spec/
---

# 0002. The kernel's rules are checked before any kernel is written

The rules that decide what counts as shown must themselves be shown to be sound, and each check must be seen to fail when the rule is broken.

## Criteria

| # | Criterion | Gate | Checked by |
|---|---|---|---|
| 1 | Every claim in spec/CLAIMS.md has a model or scenario | hard | 12 of 37 checked by a model, 5 more sampled by the kit, 11 modelled and waiting for a run of the rewritten models; see spec/CLAIMS.md. Not an obligation a kernel can read yet |
| 2 | Every modelled claim has a planted defect that is caught | hard | Every planted-defect case of every model, as obligations of the model-checker provider |
| 3 | Every modelled claim has a completed, recorded run | hard | Every design case of every model, as obligations of the model-checker provider |
