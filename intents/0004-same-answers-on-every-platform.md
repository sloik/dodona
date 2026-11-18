---
id: "0004"
title: The same project gives the same answers on every platform
owner: project owner
worker: the agents building dodona
parent: "0001"
touches:
  - conformance/vectors
  - protocol/
---

# 0004. The same project gives the same answers on every platform

What is set up on one operating system gives the same results on another: macOS first, then Linux, then Windows.

## Criteria

| # | Criterion | Gate | Checked by |
|---|---|---|---|
| 1 | The canonical encoding and the path check exist as test vectors | hard | conformance/vectors/, checked by the repository checks. Not an obligation a kernel can read yet |
| 2 | The vectors give identical results on macOS and Linux | hard | Both kernels are judged with the vectors on both in CI. Not an obligation a kernel can read yet |
| 3 | The vectors give identical results on Windows | deferred | Both kernels are judged with the vectors on Windows in CI. Not an obligation a kernel can read yet |
