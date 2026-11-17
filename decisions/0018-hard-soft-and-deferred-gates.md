---
id: "0018"
title: Hard, soft and deferred gates
status: proposed
direction: owner
date: 2026-11-17
governs:
  - MODEL.md
supersedes: []
---

# 0018. Hard, soft and deferred gates

## Context

Refusing to deliver anything unproven is the right default and cannot be the whole rule. Some things can only be seen on a live system after delivery, some cannot be mocked, and some systems behave differently from run to run. Pretending otherwise produces either a tool nobody can use or checks that are quietly weakened.

## Decision

Every criterion is tied to its obligations through a **gate**, declared up front by the intent owner:

- **Hard**: must pass before delivery. This is the default.
- **Soft**: is checked and reported, lowers the stated assurance when it does not pass, and does not block delivery.
- **Deferred**: cannot be checked before delivery, such as behaviour on a live system. It has a stated condition and time limit. The intent can be delivered while it is open, is not *fulfilled* until it closes, and is reported as overdue when its limit passes.

A check on something that varies from run to run declares that in advance: how many runs, and how many must agree. Its result is the measured rate with the number of runs, never a single lucky pass. Disagreement that was not declared in advance remains a conflict.

Gates are part of what the owner confirms before work starts, so declaring them is not a free choice of the agent doing the work, and changing one later is an amendment. Policy sets a floor: a minimum of hard gates, a longest limit for a deferred gate, and minimum runs and agreement for a varying check. An intent with no hard gate, or fewer than policy demands, is reported as `unguarded` and never as delivered.

An intent is **delivered** when every hard gate has passed at the level policy demands. It is **fulfilled** when every deferred gate has closed as well. dodona never reports either state otherwise.

## Consequences

- Real-world mess has a named, visible place instead of being hidden in a weakened check.
- "Delivered" and "fulfilled" are different words, so a live check that has not happened yet is not mistaken for one that passed.
- A flaky result is a number with a sample size.

## Alternatives rejected

- Hard gates only: forces people to fake what cannot be checked.
- Let the agent doing the work decide what blocks: the weakest agents would have the weakest gates.

## What would show this wrong

An intent is reported delivered with a hard gate not passed, or fulfilled with a deferred gate still open, a varying check is reported as passed from one run, or an intent whose gates are all soft or deferred is reported as delivered.
