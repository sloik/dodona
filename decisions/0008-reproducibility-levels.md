---
id: "0008"
title: Reproducibility through a lock, at a level the agent chooses
status: accepted
date: 2026-11-17
governs:
  - ARCHITECTURE.md
  - protocol/
supersedes: []
---

# 0008. Reproducibility through a lock, at a level the agent chooses

## Context

A project configured on one platform must give the same answers on another. Byte-identical output across operating systems is impossible for many solvers and compilers, so demanding it everywhere would exclude most tools.

## Decision

Configuration states intent; a generated lock pins every provider and tool. A tool is a directory tree, and its digest is the hash of a canonical listing of that tree, independent of how it was packaged. A tool declares what it requires, such as a language runtime, and the whole closure is pinned. Each lock entry has one digest per platform and the upstream source the digest was verified against. The lock is committed, identical on every platform, and replaced atomically.

The guarantee has three levels, chosen per obligation or build target: `verdict` (default; same verdict everywhere), `evidence` (the provider's declared comparable summary is equal), `artifact` (byte-identical outputs, only where the provider declares it). Asking for a level a provider cannot meet fails at resolve time.

Records with the same core key and different platforms are compared at the chosen level. Disagreement is a failed reproducibility obligation. If only one platform has run, reproducibility is `unknown`. A provider's claim of platform independence never removes the platform from a record; it only lets a record from one platform stand in for another once the claim has been checked on two.

## Consequences

- Adding a platform adds lock entries and never changes existing ones.
- A tool with no build for a platform makes its obligations `unsupported` there, visibly.
- Reproducibility is itself checked and recorded, not assumed.

## Alternatives rejected

- Byte-identical everywhere: excludes most real tools.
- Delegate to an existing package manager: none covers macOS, Linux and Windows natively. A toolchain provider may wrap one.

## What would show this wrong

The same lock and sources give different verdicts on two platforms and dodona does not report it.
