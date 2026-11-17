---
id: "0020"
title: Exceptions are granted by the intent owner, and recorded
status: proposed
direction: owner
date: 2026-11-17
governs:
  - MODEL.md
supersedes: []
---

# 0020. Exceptions are granted by the intent owner, and recorded

## Context

Things change after work starts: a criterion turns out to be wrong, a check cannot be built, a live run has to stand in for a proof. Someone has to be able to say so. If the agent doing the work can say so freely, the guarantee is gone; if nobody can, the tool is unusable.

## Decision

Any difference from the baseline the owner confirmed is an **amendment**: changing a criterion, moving a gate, extending a limit, lowering a sample size or threshold, declaring a check to be varying, re-linking a criterion to a different check, adding or removing a child, retiring conflicting records. A change to policy itself, such as switching off the independent-approver requirement, is recorded and reported in the same way. An amendment records what changed, from what to what, why, and who granted it.

Only the owner of the intent can grant one. The owner may be a person or an agent; either way the identity is recorded. Whoever does the work can request an amendment and cannot grant it. **The risk, stated plainly.** If the party that owns an intent also does the work, it can approve its own exceptions, and a weak agent could reach "delivered" without showing anything. The guarantee then rests on nothing but that agent's word.

**Best practice: the one who grants an exception is never the one whose work is being judged.** Give the intent an owner that is separate from whoever does the work: a person, or a different agent with no part in the work.

dodona supports that practice by grading it ([0024](0024-separation-is-graded-not-enforced.md)). Every amendment carries a **separation** level: how separate its grantor was from the work, from `self` up. The level leads every report that rests on the amendment. An amendment granted at `self` caps the affected criterion at `asserted`. And a project's policy sets the lowest level at which an amendment takes effect; below it the amendment is recorded and the gate stays closed. `apart` is the recommended floor, and dodona's own repository uses it.

**Independence is only as good as identity.** An agent that can invent a second identity can approve its own work under another name. How identities are established is not designed yet. Until an owner's identity is bound to something the working agent cannot create, the top level of the scale cannot be granted and levels above `helper` are usually marked `declared`.

## Consequences

- There is an honest way through every gate, and it leaves a mark.
- The authority to lower the bar belongs to whoever set it, which answers who may change what must pass.
- A self-granted exception can never look like a separate one, and a project can rule it out entirely.
- Where the floor is low, the guarantee is weaker, and every report says so.

## Alternatives rejected

- Humans only: the owner of an intent is not always a person.
- No exceptions: see the previous decision.
- Exceptions without a record: indistinguishable from a weakened check.

## What would show this wrong

A gate is passed, moved or dropped with no amendment on record, a report rests on an amendment without saying so, or an amendment is shown at a higher separation level than the one it was granted at.
