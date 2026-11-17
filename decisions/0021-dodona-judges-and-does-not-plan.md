---
id: "0021"
title: dodona judges; it does not plan or do the work
status: proposed
direction: owner
date: 2026-11-17
governs:
  - ARCHITECTURE.md
supersedes: []
---

# 0021. dodona judges; it does not plan or do the work

## Context

dodona is used by agents, some of them not very capable. It could help them by guiding their next step or by handing out work in small pieces. Each of those is a larger product with its own risks.

## Decision

For now dodona judges only. It says what was defined, what has been shown, how strongly, what is missing and why, and it explains any of its answers on request. It does not choose the next step, break work down by itself, or do any of the work.

Its answers are written so that a less capable agent can act on them without understanding the whole system: every result names the exact thing concerned, the reason in a fixed vocabulary, and what evidence would change it. That is description of the gap, not direction of the work.

This is to be revisited once dodona has been used on itself.

## Consequences

- The judge has no stake in the work it judges.
- Guidance and work breakdown remain possible later, as something built on top.

## Alternatives rejected

- Guide the next step, or plan and hand out work: more help for weak agents, a bigger and less neutral tool. Deferred, not rejected.

## What would show this wrong

dodona's output tells an agent what to do next instead of what is not yet shown, or dodona changes the work it is judging.
