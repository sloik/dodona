---
id: "0038"
title: A site can set a minimum batch wait
status: proposed
date: 2026-11-26
governs:
  - conformance/project/
  - conformance/README.md
  - kernel/src/project_status.rs
  - kernel2/project-run.js
  - tools/project_run.py
supersedes: []
amends:
  - "0034"
---

# 0038. A site can set a minimum batch wait

## Context

The time an executor needs to admit and finish a batch can exceed the longest run in it. The executor may wait for shared capacity or run the cases in sequence. A kernel waiting only for the longest run plus a minute can end a batch that the executor could still finish.

## Decision

A site may supply `batch_wait_floor_ms` in a project `run` request. It must be a whole number from 1 through 86,400,000. A malformed value is refused before providers or the executor start.

The kernel waits at least this long for each batch, subject to the existing 24-hour cap. It also keeps the existing wait based on the longest run's limit plus one minute. The absence of a run limit still gives a 24-hour wait. Requests without a batch floor keep their current wait.

Run descriptions and their keys use the provider's original limits. The floor changes how long the kernel waits for an executor's answer. Timed-out and unavailable batches retain their existing verdict rules.

## What would show this wrong

- A shorter floor reduces the wait promised by a run's limit.
- A longer floor changes a run description or the run key.
- A batch that misses its deadline can produce a passing result.
- A site can give an invalid floor and still start a provider or submit a batch.
