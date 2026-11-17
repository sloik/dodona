---
id: "0002"
title: Small kernel; everything else is a provider
status: proposed
direction: owner
date: 2026-11-17
governs:
  - ARCHITECTURE.md
supersedes: []
---

# 0002. Small kernel; everything else is a provider

## Context

Projects must be able to bring their own decision format, verification tools and compilers, and combine them freely. Any tool the kernel knows about becomes a tool every user is forced to accept.

## Decision

The kernel knows the graph, identity, the resolver, the planner, the ledger, policy, the provider protocol and the agent interface. It contains no knowledge of any language, checker, compiler or decision format.

Each replaceable part is a provider kind with named capabilities. A project configures which provider supplies each capability. The earlier comparison of two foundations (TLA+ with Unison, Dafny with Go and JavaScript) is not resolved by picking a winner: both become provider combinations, and the comparison's scenario corpus becomes the conformance kit.

## Consequences

- The kernel stays small enough to specify formally in full.
- The protocol becomes the most important interface in the project and must be versioned from the first message.
- dodona ships reference providers, but none is privileged.

## Alternatives rejected

- A built-in default stack with plugins as an extension: the default would shape every contract around itself.
- Pick the winning foundation first: delays the contracts and bakes one tool's assumptions into them.

## What would show this wrong

A provider needs a change inside the kernel to be supported, or the kernel's source names a specific tool.
