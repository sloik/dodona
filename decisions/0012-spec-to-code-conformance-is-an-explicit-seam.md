---
id: "0012"
title: Specification-to-code conformance is an explicit seam
status: proposed
date: 2026-11-17
governs:
  - ARCHITECTURE.md
supersedes: []
---

# 0012. Specification-to-code conformance is an explicit seam

## Context

A checked model proves things about the model. Whether the code behaves like the model is a separate question, answered differently by each approach: some prove it by construction, some test traces, some only document a mapping.

## Decision

Linking a specification to an implementation is its own obligation, checked by a `conformance.check` provider. Its evidence states the **method** (for example proof by construction, refinement, trace replay, or a mapping that is only documented) and the trusted base, including any code the proof does not reach, such as foreign-function shells.

A build step between a verified source and what actually runs is part of the same chain: the build is an obligation, its output is a node, and what consumes the output depends on it.

Evidence class and method are provider-named values with a declared strength, not a fixed list in the kernel. Results are reported per layer. "Specification verified" and "implementation conforms" are never merged into one green result.

## Consequences

- A weak conformance method is visible as weak.
- Where specification and code are the same language, the provider reports `proof` with a small trusted base; the seam remains, and is simply cheap.

## Alternatives rejected

- Treat a passing model as covering the code: the central false claim this project exists to prevent.

## What would show this wrong

A report shows an implementation as verified when only its model was checked.
