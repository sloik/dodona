---
id: "0001"
title: Decisions are first-class nodes
status: accepted
date: 2026-11-17
governs:
  - decisions/
supersedes: []
---

# 0001. Decisions are first-class nodes

## Context

Design reasons usually live in documents that nothing checks. They go stale without anyone noticing, and an agent arriving later cannot tell which reasons still apply.

## Decision

Every decision is a node in dodona's graph. A decision record states its status, what it governs, and what it supersedes.

`governs` names definitions by their stable name, and the kernel records the content identity each name had when the decision was written. When the identity behind a governed name changes, or the name disappears, the decision is flagged for review. Until an index exists, the names in this directory are repository paths.

The decision format is a provider. The default is Markdown with a small header, used in this directory. A formal decision language is equally valid: the layer exists to capture context, alternatives and reasons, in whatever form a project chooses. A provider maps its own status vocabulary onto `proposed`, `accepted`, `superseded` and `rejected`.

## Consequences

- When a governed definition changes, the decision is flagged for review.
- A superseded decision stays in the graph; history is never rewritten.
- Until the kernel exists, links in this directory are checked by hand.

## Alternatives rejected

- Decisions as free prose outside the graph: cannot be invalidated by change.
- Decisions only as formal specifications: loses the rejected alternatives and the context, which is the part worth keeping.

## What would show this wrong

A governed definition changes and no decision is flagged, or a decision can be edited in place without a superseding record.
