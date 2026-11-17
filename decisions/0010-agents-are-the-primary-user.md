---
id: "0010"
title: Agents are the primary user
status: accepted
date: 2026-11-17
governs:
  - ARCHITECTURE.md
supersedes: []
---

# 0010. Agents are the primary user

## Context

dodona is driven by AI agents. Interfaces designed for people force agents to parse prose, guess at state and answer prompts.

## Decision

Every command takes structured input and returns structured output described by a published schema. Errors have stable codes. Nothing prompts. Output order is deterministic. Every result can be asked to explain itself: why an obligation is stale, what a verdict rests on.

Human-readable output is a rendering of the structured result, never a separate source of information.

## Consequences

- The command schema is part of the public contract and is versioned.
- Anything a person can learn from dodona, an agent can learn without scraping.

## Alternatives rejected

- A conventional command line with an optional machine mode: the machine mode is always the one that lags.

## What would show this wrong

Some state or reason is available only as prose, or a command blocks waiting for input.
