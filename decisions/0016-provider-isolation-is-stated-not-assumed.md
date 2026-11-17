---
id: "0016"
title: Provider isolation is stated, not assumed
status: proposed
date: 2026-11-17
governs:
  - ARCHITECTURE.md
  - protocol/
supersedes: []
---

# 0016. Provider isolation is stated, not assumed

## Context

A provider and the tools it runs are ordinary programs. Operating systems differ widely in how well a process can be confined, and some confinement mechanisms are unavailable in common environments. Claiming that providers have no access beyond their declared inputs would be untrue on at least one supported platform.

## Decision

The kernel confines providers and tools as far as the platform allows and records the level achieved for every run: `enforced` (reads and writes outside the declared inputs and outputs are prevented), `best-effort` (a private working copy and a cleaned environment, but no enforcement), or `none`.

The level appears in every status. Policy can require a minimum. At any level below `enforced`, "the provider declared all its inputs" stays a trusted assumption and is reported as one.

Regardless of level: inputs are a private copy, the environment passed to a child is explicit and minimal, and the kernel never follows a link when reading outputs.

## Consequences

- Results are honest about a weakness instead of hiding it.
- The same project may reach different isolation levels on different platforms; that is visible in the records.

## Alternatives rejected

- Require enforcement everywhere: would exclude platforms and environments where it cannot be had.
- Say nothing: the default in most tools, and the reason undeclared inputs go unnoticed.

## What would show this wrong

A record claims `enforced` for a run in which the tool read a file outside its declared inputs.
