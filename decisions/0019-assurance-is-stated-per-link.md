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

Between an intent in plain words and a running system there are links of two different kinds, and dodona reports them separately.

**Judgement links** can only ever be someone's word: whether the written criteria say what was meant, and whether a given check really tests a given criterion. dodona cannot judge these and says so. It records whose word it is, ties that word to an exact identity of what was confirmed, and shows whether that party is independent of the work.

**Evidence links** are what can be shown: how the code was checked against the specification, whether what was delivered is the thing that was checked, and whether it was observed working where it is used. Each has a level from one ordered scale: `proven` for all cases, `bounded` (all cases within stated limits), `sampled` (some cases, with the count), `observed` (seen working live), `asserted` (someone says so), `none`.

Every evidence link is always evaluated; one with nothing reported is `none`. A criterion's shown level is its **weakest evidence link**, never an average. The score of an intent is a plain count: how many criteria reach the level policy demands for their gate, out of how many. Where a figure is a real measurement, such as a pass rate, it is shown with its sample size. dodona does not invent probabilities.

The status word is never reported alone. Every result leads with the gate mix, the shown level and where the weakest link is, who agreed the judgement links, the exceptions, and whether independence is verified.

## Consequences

- A less capable agent, or a person, gets one comparable answer and can see exactly which link holds it down.
- Weak mapping between specification and code is visible as a low level on that link instead of being absorbed into a pass.
- Two projects' scores mean the same thing, because the scale and the rule are fixed.

## Alternatives rejected

- One percentage for everything: looks precise and averages away the weak link.
- Pass or fail only: says nothing about how much was actually checked.

## What would show this wrong

A criterion is reported at a level higher than its weakest evidence link; an unreported link raises a score; a judgement link is shown as if it were evidence; or a status is shown without its headline.
