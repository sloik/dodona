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

A check, which may consist of several tool runs, ends in exactly one of `passed`, `failed`, `pending`, `unavailable`, `error`, `unsupported`. The set is defined by the kernel and providers cannot extend it. A tool that answers "unknown" yields `error`. A result that holds only by relying on something policy does not allow, such as an unproven assumption inside a proof, is `failed`.

Only `passed` and `failed` are reusable. Nothing converts another verdict into `passed`: not a retry policy, not a default, not a provider.

The status of an obligation is derived by the kernel from all reusable records for its current evidence key: `passed` if they all pass, `failed` if they all fail, `conflict` if they disagree, `unknown` with a reason if there are none. A pass never outranks a recorded failure. A rerun adds a record and never replaces one.

A project is `passed` only when policy requires at least one obligation and every required one is `passed`. A project where nothing was required or nothing ran is never reported as passing.

## Consequences

- Agents get a total, stable set to branch on.
- "Could not check" is always visible and never green.
- Providers with richer outcomes map them onto this set and attach detail as evidence.

## Alternatives rejected

- A boolean result: cannot tell "false" from "did not run".
- Provider-defined verdicts: every consumer would need per-provider knowledge.

## What would show this wrong

Any sequence of events makes an obligation report `passed` without a completed check whose result was a pass for the current inputs, or while a failure is recorded for the same inputs. Modelled in `spec/kernel/EvidenceReuse.tla` (properties `Provenance` and `NoPassOverFail`, with a planted defect for each).
