---
id: "0015"
title: Ledger integrity, and trust in records from elsewhere
status: proposed
date: 2026-11-17
governs:
  - ARCHITECTURE.md
  - protocol/evidence-record.schema.json
supersedes: []
---

# 0015. Ledger integrity, and trust in records from elsewhere

## Context

A record's identity is a hash anyone can compute, so by itself it proves nothing about who wrote the record or whether a check ever ran. Shared stores make reuse across machines possible and make forged or corrupted records possible too.

## Decision

The ledger has a single writer at a time, enforced by a lock on the project. Records are framed with a length and checksum. A torn final record is detected at start, discarded and reported. The kernel reports only what is durably written; if a record cannot be written, the run's outcome is `error`.

Every record names its origin. Records written by this kernel are trusted. Records obtained from anywhere else are not reusable until policy names their origin as acceptable and their signature verifies. Whenever any record is read, its key is recomputed from its stated inputs.

Records are ordered by causal predecessor, not by a counter or a clock, so two machines never contend for the same position.

## Consequences

- A hand-written record in a shared store is ignored unless it is signed by an origin policy accepts.
- Sharing evidence between machines requires key management, which is extra work and is not designed yet.
- Local write access to the ledger remains in the trusted base.

## Alternatives rejected

- Trust the store: one poisoned or mistaken write turns into a pass everywhere.
- No sharing at all: every machine would recheck everything.

## What would show this wrong

A record that no trusted kernel wrote is reused, or a crash leaves the ledger in a state that changes a reported status without being reported.
