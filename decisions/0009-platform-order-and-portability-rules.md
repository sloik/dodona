---
id: "0009"
title: Platform order, and portability rules that apply from day one
status: proposed
direction: owner
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

- No shell. Commands are argument lists. The program is an exact file inside a pinned tool tree; nothing is found by searching. Script wrappers that re-parse arguments through a command interpreter are not valid entry points.
- Paths pass one normative check, published with test vectors: valid UTF-8, Unicode NFC or rejected, `/` separators, no empty, `.` or `..` segments, no character or reserved name that any supported platform cannot represent, no trailing dot or space, bounded length, and no two paths equal under case folding.
- File content is hashed as raw bytes. The project declares its line-ending and byte-order-mark convention; a violation in a text file is an error, never normalised away. Which files are text is declared by the provider claiming them.
- Symbolic links and similar indirections inside a project are rejected. File modes never take part in identity.
- A platform is `os`, `arch` and, where it matters, the C library, each from a closed list. It is data in the lock, never a code path in configuration.
- Message framing is exact: UTF-8, one line-feed byte as delimiter, no byte-order mark, bounded line length.
- A timed-out or cancelled run has its whole process tree terminated.

The rules are tested now, on the first platform, with vectors that are data instead of real files with hostile names, and with a deliberately misbehaving test provider.

## Consequences

- The first Linux and Windows runs are expected to find defects in implementations, not in the design.
- Some convenient macOS-only shortcuts are forbidden now.

## Alternatives rejected

- Design for macOS and port later: the hashing and path rules would change, invalidating every recorded identity.

## What would show this wrong

A project's lock or identities differ depending on the platform that generated them.
