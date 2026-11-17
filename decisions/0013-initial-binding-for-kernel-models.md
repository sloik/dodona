---
id: "0013"
title: TLA+ is the initial binding for dodona's own kernel models
status: proposed
date: 2026-11-17
governs:
  - spec/
  - dodona.toml
supersedes: []
---

# 0013. TLA+ is the initial binding for dodona's own kernel models

## Context

dodona's own specification has to be written in something before dodona exists to choose. The kernel's hardest properties are about orderings: edits racing with running checks, executors disappearing.

## Decision

The kernel models in `spec/` are written in TLA+ and checked with TLC. This is a binding in dodona's own configuration, not part of the architecture: it can be replaced or joined by another specification provider, and properties that must hold for all inputs of a pure function may be better served by one.

No model is described as checked unless a model-checker run is recorded for it.

## Consequences

- Readers need TLA+ to follow the kernel models.
- Claims about all-input properties remain `not yet modelled` until a suitable provider is bound.

## Alternatives rejected

- Wait for dodona to exist: leaves the architecture unverified exactly when it is cheapest to change.

## What would show this wrong

A property that matters cannot be expressed in the bound language and is silently dropped instead of listed as not modelled.
