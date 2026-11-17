---
id: "0009"
title: Platform order, and portability rules that apply from day one
status: accepted
date: 2026-11-17
governs:
  - ARCHITECTURE.md
supersedes: []
---

# 0009. Platform order, and portability rules that apply from day one

## Context

Support arrives in order: macOS, Linux, Windows, then others. Portability problems are cheap to prevent in the first design and expensive to remove later.

## Decision

These rules bind the kernel, the protocol and reference providers from the start, although only macOS is exercised at first:

- No shell. Commands are argument lists.
- Paths in configuration, lock and protocol are relative, use `/`, and are Unicode NFC. Case-only collisions and names unrepresentable on a supported platform are rejected at index time.
- File content is hashed as raw bytes; the line-ending convention is enforced, not normalised.
- No reliance on symbolic links, file modes, or case sensitivity of the file system.
- Platform is `os` plus `arch` plus, where it matters, the C library; it is data in the lock, never a code path in configuration.
- All text exchanged is UTF-8.

## Consequences

- The first Linux and Windows runs are expected to find defects in implementations, not in the design.
- Some convenient macOS-only shortcuts are forbidden now.

## Alternatives rejected

- Design for macOS and port later: the hashing and path rules would change, invalidating every recorded identity.

## What would show this wrong

A project's lock or identities differ depending on the platform that generated them.
