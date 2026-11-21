---
id: "0031"
title: An agreement after a change keeps its grade, up to a limit on refusals along the line
status: proposed
direction: owner
date: 2026-11-18
governs:
  - spec/attempts/Attempts.tla
  - conformance/README.md
supersedes: []
amends:
  - "0024"
---

# 0031. An agreement after a change keeps its grade, up to a limit on refusals along the line

## Context

Decision 0024 grades how separate a checker was and caps at `helper` an agreement that follows a refusal, so that asking again until one agrees ("shopping") earns nothing. The data model capped only when the thing judged had not changed between tries. Decision 0024 also says a trivial change made to get a fresh try must not reset the count. A kernel cannot tell a real fix from a trivial change.

Capping every agreement after any refusal, whatever changed, removes shopping but also grades an honest fix-and-recheck as `helper` for ever. Capping only unchanged work lets a cosmetic change buy a fresh try at full grade. The owner chose between these on 2026-11-18.

## Decision

- Every attempt along a line (the same criterion of the same intent) is counted, across changes of what is judged, and the count is reported.
- An agreement that follows an attempt that did not agree is reported as **retried**.
- An agreement after one that did not agree on the **same** target is **shopped** and capped at `helper`.
- After a change of target, a retried agreement keeps its grade until the line has as many attempts that did not agree as policy allows (`refusals_before_cap`, default 2). From then on every retried agreement on the line is capped at `helper`.
- The cap never raises a level. A limit of one gives the strictest rule: no agreement after any refusal earns more than `helper`.

## Consequences

- An honest fix that is approved after one refusal keeps its full grade, and is visibly marked retried.
- Repeated cosmetic changes stop paying off once the limit is reached; the limit is policy, so a project can make it stricter.
- The attempts model and the kernel conformance kit check this rule, with planted defects for the two rules rejected (capping every retry, and ignoring the limit).

## What would show this wrong

- An agent that reaches a full grade by making trivial changes until a checker agrees, more often than the limit allows, would show the count of refusals not kept along the line.
- An honest fix approved after a single refusal and graded `helper` would show the rule applied more strictly than decided.
- If in practice most lines reach the limit through honest work, the default of two is too strict.
