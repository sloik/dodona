---
id: "0017"
title: Work starts as intent in plain words, and breaks down
status: proposed
direction: owner
date: 2026-11-17
governs:
  - MODEL.md
  - intents/
supersedes: []
---

# 0017. Work starts as intent in plain words, and breaks down

## Context

What someone wants begins as a problem, a feature or a story in ordinary language. Some intents are too large to deliver or too vague to check, and work that cannot be split cannot be done in parallel. At the same time dodona must not become a project tracker.

## Decision

An **intent** is a node: a statement in plain words, an owner, and a list of **criteria**, each a single thing that must be true for the intent to count as met. The owner is whoever is behind the intent, a person or an agent, and is recorded.

An intent can be broken into child intents. A parent is met when its children are met and its own criteria, which are about the parts working together, are met. Each intent declares what it expects to touch, so intents that touch nothing in common can be worked on in parallel, and two that collide are reported before work starts.

Each criterion is linked to the obligations that check it. A criterion with no obligation is reported as uncovered; it does not silently count.

Everything else about an intent is derived, never set by hand: whether it is covered, delivered or fulfilled follows from evidence. dodona stores no assignees, estimates, schedules or workflow states.

## Consequences

- The chain from "what was wanted" to "what was built" is in one graph.
- Breaking work down is a normal act with a recorded shape, not a side document.
- dodona can say which intents are safe to work on at the same time.
- A separate tracker can sit on top; dodona does not replace one.

## Alternatives rejected

- Start from a precise specification only: leaves the gap between what was meant and what was written outside the tool, which is where much of the loss happens.
- A full work tracker: a different product, and state set by hand is exactly what cannot be trusted.

## What would show this wrong

An intent is reported as met while one of its criteria has no passing check and no recorded exception, or its status can be changed without any evidence changing.
