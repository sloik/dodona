---
id: "0024"
title: Separation of the checker from the work is graded, not enforced
status: proposed
direction: owner
date: 2026-11-17
governs:
  - MODEL.md
  - protocol/act-record.schema.json
  - spec/intent/IntentGates.tla
supersedes: []
---

# 0024. Separation of the checker from the work is graded, not enforced

## Context

A check, a review or an approval is worth little if the party that did the work also did the checking. Agents can and should start other agents as verifiers, reviewers and approvers. dodona cannot make them truly independent: an agent can start a copy of itself, hand it its own conclusions, tell it what to find, run it again until it agrees, or act under a second name.

Earlier drafts said `independence: verified` or `unverified`. "Verified" would have been untrue in almost every case.

The design below was put together from three independent proposals, written from the viewpoints of audit and safety assurance, of building multi-agent systems, and of a weak agent that reads only the first line.

## Decision

dodona does not claim to enforce independence. It **grades** how separate the checker was from the work, on one scale, for every act that rests on someone's judgement, and reports the grade next to the status.

**The scale, called separation**, weakest first:

| Level | Meaning | What must be on record |
|---|---|---|
| `self` | The party that did the work also did this, or nothing is recorded | Nothing. This is the default |
| `helper` | Someone else, but started or briefed by the worker, or shown the worker's reasoning or conclusions | A different actor and session |
| `apart` | A fresh session that saw only the thing to judge and the criteria, with a brief the worker did not write | The brief and who issued it; the list of everything the checker was given, by content hash |
| `tested` | `apart`, and the checker was shown at least one known-bad case and rejected it, with every attempt on record | The known-bad case and its rejection; the full list of attempts |
| `cross-make` | `tested`, and the checker is a different make from the worker: another model family or vendor, or a deterministic tool | The checker's make, as reported by whatever ran it |
| `credentialed` | `cross-make`, and the record is signed with a credential the worker cannot create | A signature that verifies against a key the worker cannot write. Not available yet |

Three questions settle most cases, and a weak agent can answer each honestly: *Who started the checker? What was it shown? Could the worker run it again until it agreed?*

**Every fact has a source, and the grade shows the weakest one.** Each fact behind a grade is `checked` (dodona recomputed it), `attested` (signed by a harness whose key policy lists) or `declared` (someone says so). The grade is always shown with its weakest source, for example `apart (declared)`. dodona only ever lowers a claimed level; it never infers a higher one from silence, from a different-looking name, or from the likelihood that a sub-agent was used.

**Where it applies.** To the acts that rest on someone's word: confirming an intent's criteria, saying that a check tests a criterion, granting an exception, closing a deferred gate by observation, and changing policy. It does not apply to a check that anyone can run again from locked inputs; there the evidence scale already says what was shown, and counting separation as well would count the same thing twice.

**It is a separate axis.** Separation is never multiplied into the evidence level and never averaged. It acts in three plain ways:

- **Shown.** The headline carries the weakest separation among the acts a result rests on, the act it belongs to, and a count: how many of those acts are `apart` or better, out of how many. That count is the partial score for independent verification.
- **Cap.** Whatever rests on an act at `self` is at most `asserted`.
- **Floor.** Policy sets a minimum level, and a minimum source, per kind of act. An act below the floor does not take effect: the exception is not granted, the intent stays a draft, the deferred gate stays open.

**Trying again is recorded.** A checker takes a ticket before each attempt. An attempt with no result counts as a failure. On an unchanged target the worst result counts, and a pass that follows a failure without the target changing is flagged and graded no higher than `helper`.

**A sensible default** for a project that has not thought about it: exceptions and policy changes need `apart`; confirming criteria and matching checks to criteria are shown and capped; an observation by the worker does not close a deferred gate.

## Consequences

- An honest weak agent that checks its own work gets an honest `self`, and loses nothing by saying so except credit it did not earn.
- The earlier yes-or-no setting for an independent approver becomes a minimum separation level in policy.
- A harness that can attest to a fresh context and to what a checker was given becomes useful, and joins the trusted base.
- `credentialed` cannot be granted until identities are bound to something a worker cannot create. Until then the scale stops at `cross-make`, and every level above `helper` usually carries the word `declared`.

## What stays unexposed

Said plainly, because a reader should know the limits:

- Steering a checker through the thing it is given to judge, such as a comment planted in the work, cannot be told apart from content.
- An agent that controls the harness, or its key, can attest to anything.
- Attempts made without taking a ticket leave no trace. They cannot earn a high level, and they cannot be counted either.
- Separation is not competence. A checker that agrees with everything is caught only by the known-bad case, and two checkers of similar make share blind spots.

## Alternatives rejected

- Enforce independence: not possible, and claiming it would be the kind of false assurance dodona exists to prevent.
- A yes-or-no flag: hides the difference between a copy of the worker and a tested checker of another make.
- Fold it into one score with the evidence level: produces a number that looks precise and means nothing.

## What would show this wrong

An act with nothing recorded is given any level but `self`; a level is reported higher than the one used; an act below policy's floor takes effect; or a report shows a separation level without its source. The first three are modelled in `spec/intent/IntentGates.tla`.
