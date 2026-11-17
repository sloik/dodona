---
id: "0005"
title: A closed set of verdicts; only a pass is a pass
status: proposed
date: 2026-11-17
governs:
  - protocol/evidence-record.schema.json
  - spec/kernel/EvidenceReuse.tla
supersedes: []
---

# 0005. A closed set of verdicts; only a pass is a pass

## Context

The common failure of verification pipelines is a check that did not run being reported as a check that passed: a timeout, an unreachable machine, a skipped step.

## Decision

A check ends in exactly one of `passed`, `failed`, `pending`, `unavailable`, `error`, `unsupported`. The set is defined by the kernel and providers cannot extend it.

Only `passed` and `failed` are reusable. Nothing converts another verdict into `passed`: not a retry policy, not a default, not a provider. An obligation with no reusable record for its current evidence key is reported as unknown.

## Consequences

- Agents get a total, stable set to branch on.
- "Could not check" is always visible and never green.
- Providers with richer outcomes map them onto this set and attach detail as evidence.

## Alternatives rejected

- A boolean result: cannot tell "false" from "did not run".
- Provider-defined verdicts: every consumer would need per-provider knowledge.

## What would show this wrong

Any sequence of events makes an obligation report `passed` without a completed check whose result was a pass for the current inputs. Modelled in `spec/kernel/EvidenceReuse.tla` (mutant `unavailable_is_pass`).
