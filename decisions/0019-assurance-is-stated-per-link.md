---
id: "0019"
title: Assurance is stated for each link, and the weakest link is the score
status: proposed
direction: owner
date: 2026-11-17
governs:
  - MODEL.md
supersedes: []
---

# 0019. Assurance is stated for each link, and the weakest link is the score

## Context

Not everything will be fully checked, and the loss does not happen in one place. An intent is turned into a definition, the definition into something formal, that into code, the code into something that runs. Each step can lose meaning, and it is hard to confirm that one maps exactly onto the next. A single green mark hides all of it.

## Decision

For every criterion, dodona reports the **assurance** of each link in the chain from intent to running system:

| Link | Question |
|---|---|
| Intent to definition | Did the owner confirm the written criteria say what was meant? |
| Definition to specification | Is the criterion covered by a formal statement, fully or in part? |
| Specification to code | How was the code checked against it? |
| Code to what runs | Was what was built and delivered the thing that was checked? |
| What runs to the world | Was it observed working where it is used? |

Each link has a level from one ordered scale: `proven` for all cases, `bounded` (all cases within stated limits), `sampled` (some cases, with the count), `observed` (seen working live), `asserted` (someone says so, and who), `none`.

The assurance of a criterion is its **weakest link**, never an average, because a chain is as strong as its weakest part. The score of an intent is a plain count: how many of its criteria reach the level their gate demands, out of how many. Where a figure is a real measurement, such as a pass rate over many runs, it is shown with its sample size. dodona does not invent probabilities.

## Consequences

- A less capable agent, or a person, gets one comparable answer and can see exactly which link holds it down.
- Weak mapping between specification and code is visible as a low level on that link instead of being absorbed into a pass.
- Two projects' scores mean the same thing, because the scale and the rule are fixed.

## Alternatives rejected

- One percentage for everything: looks precise and averages away the weak link.
- Pass or fail only: says nothing about how much was actually checked.

## What would show this wrong

A criterion is reported at a level higher than its weakest link, or a number is shown that no recorded evidence produced.
