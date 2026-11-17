---
id: "0003"
title: Providers are separate processes speaking a versioned protocol
status: proposed
date: 2026-11-17
governs:
  - protocol/
supersedes: []
---

# 0003. Providers are separate processes speaking a versioned protocol

## Context

Providers are written by other people in other languages, and must work on every supported operating system. The kernel must survive a provider that crashes, hangs or lies about its output shape.

## Decision

A provider is an executable. The kernel starts it and exchanges newline-delimited JSON messages over standard input and output. The first exchange negotiates the protocol version and the capabilities offered. Every message is validated against the published schema; an invalid message ends the session with verdict `error`.

Providers receive no ambient authority: inputs arrive as declared paths in a prepared directory, and anything else a provider reads must be declared as an input.

## Consequences

- Any language that can read and write text can implement a provider.
- Process start-up cost is paid per session, so the protocol supports many requests per session.
- No shared memory and no callbacks: the kernel drives, the provider answers.

## Alternatives rejected

- In-process plugins (shared libraries): ties providers to the kernel's language and platform.
- Sandboxed modules only (for example WebAssembly): attractive for isolation, but most verification tools cannot be compiled that way today. Left open as a second transport.
- A network service: adds deployment and authentication to every local use.

## What would show this wrong

A provider cannot be written without linking kernel code, or a malformed provider message can produce a `passed` verdict.
