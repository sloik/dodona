---
id: "0006"
title: Evidence is reused by key, and the trusted base is listed
status: proposed
date: 2026-11-17
governs:
  - spec/kernel/EvidenceReuse.tla
  - protocol/evidence-record.schema.json
supersedes: []
---

# 0006. Evidence is reused by key, and the trusted base is listed

## Context

Rerunning only what changed is safe only if the system knows everything a result depended on. A stale pass is worse than no result.

## Decision

Each record carries an evidence key: a hash over the obligation's specification and target identities with their dependency closure, the provider identity and version, the protocol version, resolved tool digests, configuration, the platform unless declared independent, and any inputs the provider declares.

The key is fixed at submission from an immutable snapshot of the inputs. The result is recorded under that key even if the project changed during the run. A record is reused only when its key equals the key computed now.

The assumptions this rests on are listed, per provider, as the trusted base: declared inputs are complete, the verdict is correct for its inputs, the hash does not collide, the executor ran what it was asked to run.

## Consequences

- Reverting a change makes old evidence valid again, correctly.
- The platform is in the key by default, so cross-platform reuse must be earned by a declaration.
- Every reported result can name the assumptions under it.

## Alternatives rejected

- Timestamps or "changed since last run": wrong after reverts, clock changes and fresh checkouts.
- Trusting providers silently: hides exactly the assumptions an agent needs to see.

## What would show this wrong

A reused `passed` record whose obligation does not hold for the current inputs. Modelled (mutants `key_omits_tool`, `complete_with_current_key`, `undeclared_dep`).
