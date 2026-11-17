---
id: "0002"
title: The kernel's rules are checked before any kernel is written
owner: project owner
parent: "0001"
touches:
  - spec/
---

# 0002. The kernel's rules are checked before any kernel is written

The rules that decide what counts as shown must themselves be shown to be sound, and each check must be seen to fail when the rule is broken.

## Criteria

| # | Criterion | Gate | Checked by |
|---|---|---|---|
| 1 | Every claim in spec/CLAIMS.md has a model or scenario | hard | 9 of 28 so far |
| 2 | Every modelled claim has a planted defect that is caught | hard | spec/kernel/expected.json and spec/intent/expected.json |
| 3 | Every modelled claim has a completed, recorded run | hard | spec/CLAIMS.md, Recorded runs |
