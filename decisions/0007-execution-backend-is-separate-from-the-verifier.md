---
id: "0007"
title: The execution backend is separate from the verifier
status: proposed
date: 2026-11-17
governs:
  - ARCHITECTURE.md
supersedes: []
---

# 0007. The execution backend is separate from the verifier

## Context

Which tool checks an obligation and where that tool runs are different choices. Heavy checks often run on another machine; the same project may run locally for one user and on a queue for another.

## Decision

`obligation.check` providers describe a run: tool, arguments, inputs, expected outputs. `run.execute` providers perform runs. A verifier never starts a tool itself.

An executor that cannot run the request returns `unavailable`. There is no automatic fallback to another executor: a fallback is a configuration choice the agent makes explicitly, and it is recorded.

## Consequences

- Moving a check to another machine changes one configuration line.
- Executor identity is recorded in evidence and is part of the trusted base.
- A site can forbid local execution of a class of tools by simply not configuring a local executor for it.

## Alternatives rejected

- Verifiers launch their own tools: every verifier would reimplement remote execution, and none could be redirected.
- Automatic local fallback: silently changes where and with what a check ran.

## What would show this wrong

A check runs somewhere the configuration did not name, or an unreachable executor yields any verdict other than `unavailable`.
