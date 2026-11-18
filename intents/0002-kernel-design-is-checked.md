---
id: "0002"
title: The kernel's rules are checked before any kernel is written
owner: project owner
worker: the agents building dodona
parent: "0001"
touches:
  - spec/
criteria: [{"id": "1", "words": "Every claim in spec/CLAIMS.md has a model or scenario", "gate": "hard", "checked_by": "24 of 37 checked by a model, 6 more sampled by the kit, 7 not yet modelled; see spec/CLAIMS.md. Not an obligation a kernel can read yet"}, {"id": "2", "words": "Every modelled claim has a planted defect that is caught", "gate": "hard", "checks": ["*/mutant_*", "*/assumption_*"], "checked_by": "Every planted-defect case of every model, as obligations of the model-checker provider"}, {"id": "3", "words": "Every modelled claim has a completed, recorded run", "gate": "hard", "checks": ["*/design*"], "checked_by": "Every design case of every model, as obligations of the model-checker provider"}]
---

# 0002. The kernel's rules are checked before any kernel is written

The rules that decide what counts as shown must themselves be shown to be sound, and each check must be seen to fail when the rule is broken.

## Criteria

<!-- criteria: written by tools/intents.py from the front matter; do not edit -->
| # | Criterion | Gate | Checked by |
|---|---|---|---|
| 1 | Every claim in spec/CLAIMS.md has a model or scenario | hard | 24 of 37 checked by a model, 6 more sampled by the kit, 7 not yet modelled; see spec/CLAIMS.md. Not an obligation a kernel can read yet |
| 2 | Every modelled claim has a planted defect that is caught | hard | Every planted-defect case of every model, as obligations of the model-checker provider |
| 3 | Every modelled claim has a completed, recorded run | hard | Every design case of every model, as obligations of the model-checker provider |
<!-- end of criteria -->
