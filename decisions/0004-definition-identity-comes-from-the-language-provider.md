---
id: "0004"
title: Definition identity comes from the language provider, with a file-level fallback
status: proposed
date: 2026-11-17
governs:
  - ARCHITECTURE.md
supersedes: []
---

# 0004. Definition identity comes from the language provider, with a file-level fallback

## Context

Selective reruns, evidence reuse and decision links all depend on knowing exactly what changed. Some languages can identify a single definition by content; most only offer files.

## Decision

The `definition.index` capability returns, for each definition: a stable **name**, a content **identity**, the names it depends on, the granularity achieved (`definition`, `module` or `file`), and the files that materialise it for a tool to read. Identity must be a function of content alone, never of time, location or machine.

The name is what decisions and obligations refer to. A change is detected as a new identity behind an existing name; without a name, an edit in a content-addressed language cannot be told apart from a deletion and an unrelated addition.

Configuration binds a provider to the files it claims. Two providers claiming the same file for the same capability is a resolve error. When no provider claims a file, the kernel uses file identity: the hash of the bytes, with dependencies taken as declared in configuration. Coarse identity causes extra reruns. It must never cause a wrong reuse.

## Consequences

- Finer granularity is an optimisation a provider can add later without changing anything else.
- A provider that under-reports dependencies breaks soundness; this is part of the trusted base and is tested by the conformance kit.

## Alternatives rejected

- One kernel-defined notion of a definition: cannot fit both a proof language and a model-checking language.
- Require per-definition identity: excludes most existing languages.

## What would show this wrong

Two different contents receive the same identity, or the same content receives different identities on two platforms.
