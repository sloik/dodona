---
id: "0025"
title: The first seed kernel, its language and what it may claim
status: proposed
direction: owner
date: 2026-11-17
governs:
  - kernel/
supersedes: []
---

# 0025. The first seed kernel, its language and what it may claim

## Context

The conformance kit exists and was committed before any kernel. dodona needs a first kernel to be judged by it. The project fixes no implementation language ([0011](0011-self-hosting-through-a-verified-seed.md)), but a first kernel has to be written in something.

## Decision

**Scope.** The first seed does only what the kit can judge: it works out obligation status and intent status from a scenario, and produces the canonical encoding of a value. It has no providers, no ledger on disk, no planner and no agent interface. It is a seed for stage 2 of the bootstrap, not a usable dodona.

**Language.** Rust, using only its standard library, with no third-party packages. The reasons: it is a compiled language with builds for all three supported platforms; it is available without installation on the machines the checks run on; and a seed with no dependencies has nothing to pin and little to trust beyond the compiler. This is a binding for this seed. A later or second kernel is free to use another language, and a second, independent one is still a goal.

**Who writes it.** The kit and the documents were written by one make of AI model. The seed is written by a different make, given only the documents, the kit and the two judging tools, and told not to read the reference path check. On the separation scale this is as much as can be claimed today: `cross-make`, `declared`.

**What it may claim.** The seed is accepted when it passes every scenario and every encoding vector, on macOS, Linux and Windows. That is evidence at the level `sampled`: scenarios and vectors, 27 and 25 when this was written and more since. It is not a proof, and it says nothing about the claims the formal models do not cover. The path check is left out of the seed, because it needs Unicode tables the standard library does not carry; the reference implementation in `tools/` stands in until a kernel embeds the pinned tables.

**The next step up, since taken.** The model checker writes out every state two of the bounded models reach, and the kernel must give the model's answer on each one. For what those two models cover, the link between model and code is now `bounded`. For everything else it is still `sampled`.

**Since then.** The seed's later work (acts, status, the ledger, core keys) was begun by that different make and finished by the make that wrote the kit. What can be claimed for those parts is `helper`, not `cross-make`. By the owner's direction of 2026-11-18 that is no shortfall: a fresh context is what is asked for, and a different make is the user's choice ([0024](0024-separation-is-graded-not-enforced.md)).

## Consequences

- There is running code judged by something that is not itself, on three platforms.
- The assurance of that code is stated as what it is: sampled.
- The seed contains a small hand-written JSON reader, which is code to review; the encoding vectors exercise it.

## Alternatives rejected

- A language with a prover, from the start: gives a stronger link, and needs a toolchain installed on every machine before anything runs. It remains the likely route for the pure core later.
- A scripting language: runs everywhere, but the helpers in `tools/` are already written in one, and a seed in the same language by the same author would be judging itself.

## What would show this wrong

The seed passes the kit on one platform and not another; a kernel with a defect the models plant passes the kit; or the seed is described anywhere as verified.
