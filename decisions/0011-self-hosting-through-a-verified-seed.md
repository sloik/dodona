---
id: "0011"
title: Self-hosting through a verified seed; no implementation language is fixed
status: accepted
date: 2026-11-17
governs:
  - ARCHITECTURE.md
  - dodona.toml
supersedes: []
---

# 0011. Self-hosting through a verified seed; no implementation language is fixed

## Context

dodona should be built with dodona and verified from the start, without committing the project to one technology stack.

## Decision

The source of truth is dodona's own decisions and formal specification, in this repository, in dodona's own formats. An implementation is a derived artefact accepted because it conforms to the specification. The implementation language is a binding in dodona's own configuration, replaceable like any other project's.

Bootstrap proceeds in stages: specification and models; a conformance kit independent of any implementation; a seed kernel in whatever language the chosen providers support; the seed running dodona's own obligations; the seed building its successor, which rebuilds itself; and a second kernel built independently from the same specification.

What each stage does and does not establish is stated. The first seed is trusted because its source and build were reviewed, and its provenance is recorded. A kernel checking or rebuilding itself adds no trust in itself. A second kernel helps only as far as it is independent: different language, libraries and authors, and different model families where agents write them. Disagreement between kernels is a `conflict`, never resolved towards the more optimistic answer.

## Consequences

- No kernel source exists until the specification and conformance kit can judge it.
- The seed is pinned by digest and treated as a tool.
- Two independent kernels are a goal, which doubles some work and removes trust in any single one.

## Alternatives rejected

- Choose a language now and write the kernel: fastest start, but the code becomes the specification.
- Never self-host: dodona would not be subject to its own rules.

## What would show this wrong

A kernel is accepted without passing the conformance kit, or two conforming kernels disagree and the kit does not detect it.
