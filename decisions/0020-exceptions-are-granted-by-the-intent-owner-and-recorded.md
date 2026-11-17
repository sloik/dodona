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

Any change to what was defined, or to how strictly it is checked, is an **amendment**: changing a criterion, moving a gate from hard to soft or deferred, accepting a varying result, retiring conflicting records. An amendment records what changed, from what to what, why, and who granted it.

Only the owner of the intent can grant one. The owner may be a person or an agent; either way the identity is recorded. Whoever does the work can request an amendment and cannot grant it. **The risk, stated plainly.** If the party that owns an intent also does the work, it can approve its own exceptions, and a weak agent could reach "delivered" without showing anything. The guarantee then rests on nothing but that agent's word.

**Best practice: the one who grants an exception is never the one whose work is being judged.** Give the intent an owner that is separate from whoever does the work: a person, or a different agent with no part in the work.

dodona supports that practice in three ways. An amendment granted by the party that did the work is marked **self-granted**, and that mark is shown first, not buried, in every report that rests on it. A self-granted amendment caps the affected criterion at the lowest level above nothing, `asserted`, and the report says the claim is unreviewed. And a project's policy can require an independent approver, in which case a self-granted amendment does not count at all and the gate stays closed. Requiring one is the recommended setting, and dodona's own repository uses it.

Amendments are never erased and never applied silently. A report on an intent states how many amendments it rests on and which criteria they touched, and the assurance of an amended criterion can be no higher than `asserted` for the part the amendment covers.

## Consequences

- There is an honest way through every gate, and it leaves a mark.
- The authority to lower the bar belongs to whoever set it, which answers who may change what must pass.
- A self-granted exception can never look like an independent one, and a project can rule it out entirely.
- Where independence is not required, the guarantee is weaker, and every report says so.

## Alternatives rejected

- Humans only: the owner of an intent is not always a person.
- No exceptions: see the previous decision.
- Exceptions without a record: indistinguishable from a weakened check.

## What would show this wrong

A gate is passed, moved or dropped with no amendment on record, a report rests on an amendment without saying so, or a self-granted amendment is shown without its mark.
