---
id: "0004"
title: The same project gives the same answers on every platform
owner: project owner
worker: the agents building dodona
parent: "0001"
touches:
  - conformance/vectors
  - protocol/
criteria: [{"id": "1", "words": "The canonical encoding and the path check exist as test vectors", "gate": "hard", "checked_by": "conformance/vectors/, checked by the repository checks. Not an obligation a kernel can read yet"}, {"id": "2", "words": "The vectors give identical results on macOS and Linux", "gate": "hard", "checked_by": "Both kernels are judged with the vectors on both in CI. Not an obligation a kernel can read yet"}, {"id": "3", "words": "The vectors give identical results on Windows", "gate": "deferred", "checked_by": "Both kernels are judged with the vectors on Windows in CI. Not an obligation a kernel can read yet", "condition": "both kernels run the vectors on Windows and give the same results as on macOS and Linux", "limit_days": 30}]
---

# 0004. The same project gives the same answers on every platform

What is set up on one operating system gives the same results on another: macOS first, then Linux, then Windows.

## Criteria

<!-- criteria: written by tools/intents.py from the front matter; do not edit -->
| # | Criterion | Gate | Checked by |
|---|---|---|---|
| 1 | The canonical encoding and the path check exist as test vectors | hard | nothing a kernel reads yet. conformance/vectors/, checked by the repository checks. Not an obligation a kernel can read yet |
| 2 | The vectors give identical results on macOS and Linux | hard | nothing a kernel reads yet. Both kernels are judged with the vectors on both in CI. Not an obligation a kernel can read yet |
| 3 | The vectors give identical results on Windows | deferred | nothing a kernel reads yet. Both kernels are judged with the vectors on Windows in CI. Not an obligation a kernel can read yet. Observed: both kernels run the vectors on Windows and give the same results as on macOS and Linux, within 30 days of delivery |
<!-- end of criteria -->
