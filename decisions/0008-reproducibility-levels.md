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

Configuration states intent; a generated lock pins every provider and tool to an exact version with one digest per platform. The lock is committed and is the same file on every platform.

The guarantee has three levels, chosen per obligation or build target: `verdict` (default; same verdict everywhere), `evidence` (same evidence summary), `artifact` (byte-identical outputs, only where the provider declares it). Asking for a level a provider cannot meet fails at resolve time. Disagreement between platforms at the chosen level is a failed reproducibility obligation.

## Consequences

- Adding a platform adds lock entries and never changes existing ones.
- A tool with no build for a platform makes its obligations `unsupported` there, visibly.
- Reproducibility is itself checked and recorded, not assumed.

## Alternatives rejected

- Byte-identical everywhere: excludes most real tools.
- Delegate to an existing package manager: none covers macOS, Linux and Windows natively. A toolchain provider may wrap one.

## What would show this wrong

The same lock and sources give different verdicts on two platforms and dodona does not report it.
