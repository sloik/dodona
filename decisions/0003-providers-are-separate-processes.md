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

A provider is an executable. The kernel starts it and exchanges UTF-8 JSON messages over standard input and output, one per line, delimited by a single line-feed byte. The first exchange negotiates the protocol version and the capabilities offered. Every message is validated against the published schema; an invalid message ends the session, and any check in flight in it gets verdict `error`.

The kernel drives and the provider answers. A capability that needs tools to run returns a run description instead of running anything; after the run it is asked to interpret the outputs and returns either a further run or a final result.

The kernel bounds every provider: a deadline per request on a monotonic clock, a maximum message size, a cap on captured error output, and termination of the whole process tree on timeout. Bulk data never travels in messages; it is passed as files in a per-run working directory.

A provider is given a private copy of its declared inputs. How strongly it is prevented from reading anything else depends on the platform and is recorded, not assumed ([0016](0016-provider-isolation-is-stated-not-assumed.md)).

While the protocol version is below 1.0 there is no compatibility promise between versions.

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
