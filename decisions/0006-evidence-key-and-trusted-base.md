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

Each record carries an evidence key in two parts.

The **core key** is a hash over a published structure: the obligation and what it expects; the identities of its specification and target definitions with their dependency closure; input artifacts, together with the inputs of the obligation that built them; the provider identity and version; the protocol version; the digest of every tool in the closure, including runtimes; and the configuration, which includes bounds, flags, seeds, worker counts and limits.

The second part is **the platform the check executed on**, as reported by the executor.

The kernel computes the key. Providers never do, and may only add declared inputs before submission. The key is fixed at submission from a private copy of the inputs, and the result is filed under it even if the project changed during the run. Status is asked for a platform. A record counts only when its core key equals the core key computed now and its platform is the one asked about; the single exception is a verified platform-independence claim, under which a record from another platform may stand in and is reported as doing so. Whenever a record is read, its key is recomputed from its stated inputs and the record is rejected on mismatch.

Every record, including a pass, carries the exit status and the digest of the raw output it was derived from.

The assumptions this rests on are kept as one list, the trusted base, in the data model. Every status reports the subset it rests on.

## Consequences

- Reverting a change makes old evidence valid again, correctly.
- The platform is in the key by default, so cross-platform reuse must be earned by a declaration.
- Every reported result can name the assumptions under it.

## Alternatives rejected

- Timestamps or "changed since last run": wrong after reverts, clock changes and fresh checkouts.
- Trusting providers silently: hides exactly the assumptions an agent needs to see.

## What would show this wrong

A reused `passed` record whose obligation does not hold for the current inputs. Modelled in `spec/kernel/EvidenceReuse.tla` (properties `Sound` and `Consistent`, a reachability case showing records are in fact reused after an unrelated change, planted defects `key_omits_tool` and `complete_with_current_key`, and two cases showing which assumptions it depends on).
