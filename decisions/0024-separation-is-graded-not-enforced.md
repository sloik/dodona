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

**A claim is not a grade.** A review showed that an agent working alone could call itself the owner, call its sub-agent the worker, and write records earning the fifth level of six, every fact resting on its own word. So the grade is not the level the record claims. It is that level, capped by who stands behind the facts:

| Who stands behind the facts | Highest level that can be granted |
|---|---|
| `declared`: someone says so, including the party that did the work | `helper` |
| `attested`: signed by a harness whose key is listed in policy, in a file the working agent cannot change | `cross-make` |
| a credential the worker cannot create | `credentialed` |

A record whose facts are only declared is therefore graded `helper` at most, and shown as `helper (claims apart)`. The claim is kept and shown, because an honest claim is still worth more than none; it is never counted as the grade. dodona works out the source of each fact itself. A record cannot say how well supported it is.

Today nothing can attest: no harness key exists and policy cannot yet be protected from the agent it constrains. **So today the highest grade anyone can be given is `helper`**, and every report says so. Starting a separate checker is still worth doing, and still earns more than checking your own work. It does not yet earn the word `apart`.

**How a level is worked out.** The worker is the whole party in control of the work: an orchestrating agent, the sub-agents it starts, and any role it gives itself. Each level needs every fact of the levels below it.

| Level | Facts needed |
|---|---|
| `helper` | The actor is not the worker, by identity and by session |
| `apart` | The actor was started by someone other than the worker. Its brief was issued by the kernel or the owner. Everything it was given is listed, each item marked as the work, the criteria or the brief. It began with no history from the worker. Its transcript is kept |
| `tested` | The actor was given, unlabelled and together, a case known to be wrong and a case known to be right, both supplied by the owner or taken from the planted defects of the check in question, and bound to the criterion being judged. It rejected the first and accepted the second |
| `cross-make` | The actor's make and the worker's make are both reported by whatever ran them, and policy's list of makes says they are different. A script or other deterministic tool is not a make: its result is evidence, graded on the evidence scale |
| `credentialed` | The record is signed with a credential the worker cannot create |

A fact that is missing counts against the level. An absent "started by" is not evidence that the worker did not start the actor.

**Where it applies.** To the acts that rest on someone's word: confirming an intent's criteria, saying that a check tests a criterion, granting an exception, closing a deferred gate by observation, and changing policy. The result of a check that anyone can run again from locked inputs is graded on the evidence scale and not here. But saying that such a check *tests the criterion* is a judgement, and is graded for every check, however rerunnable.

**The acts are counted by the kernel, not by whoever reports.** For an intent the kernel works out the acts there must be: one confirmation, one statement per link between a criterion and a check, one per exception, one per deferred gate closed. An act with no record is an act at `self`. The count in the headline is out of that expected number, so leaving acts out lowers the score.

**It is a separate axis.** Separation is never multiplied into the evidence level and never averaged. It acts in three plain ways:

- **Shown.** The headline carries the weakest separation among the acts a result rests on, the act it belongs to, and a count: how many of those acts are `apart` or better, out of how many. That count is the partial score for independent verification.
- **Cap.** Whatever rests on an act at `self` is at most `asserted`, whatever floor policy sets.
- **Floor.** Policy sets a minimum level, and a minimum source, per kind of act. An act below the floor does not take effect: the exception is not granted, the intent stays a draft, the deferred gate stays open.

**Trying again is recorded.** A checker takes a ticket before each attempt. An attempt with no result counts as a failure. Attempts are counted along the line of the thing judged, the same criterion of the same intent, so a trivial change to the work does not reset the count. The worst result counts, a pass that follows a failure is flagged and graded no higher than `helper`, and the number of attempts is shown. *Amended by [decision 0031](0031-an-agreement-after-a-real-change-keeps-its-grade-up-to-a-limit.md) (owner direction, 2026-11-18): an agreement on the same target after a failure is capped at `helper`; after a change of target it keeps its grade until the line reaches the policy's limit of failures, two by default, and is capped from then on. The count is kept across changes as above.*

**A sensible default** for a project that has not thought about it: exceptions and policy changes need `apart`; confirming criteria needs `helper`; matching checks to criteria is shown and capped; an observation by the worker does not close a deferred gate. With nothing able to attest yet, a floor of `apart` cannot be met, which means that for now no exception can take effect at all. That is the strict reading of refusing by default, and it is intended.

**Owner direction, 2026-11-18.** Independence means a fresh context: a checker or a second author that has not seen what it judges, so that its judgement is not biased by it. A different make of model is not a must. It stays on the scale as a level a project may ask for, and whether to use one is the user's decision, taken where it gives a higher chance of success. Nothing in dodona treats work by the same make as deficient for that reason alone.

## Consequences

- An honest weak agent that checks its own work gets an honest `self`, and loses nothing by saying so except credit it did not earn.
- The earlier yes-or-no setting for an independent approver becomes a minimum separation level in policy.
- A harness that can attest to a fresh context and to what a checker was given becomes useful, and joins the trusted base.
- Until a harness can attest and policy can be protected, every grade is `self` or `helper`. The upper levels are defined so that the path is clear, and are marked as not yet grantable wherever they are shown.

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

An act with nothing recorded is given any level but `self`; a claim resting only on declaration is graded above `helper`; a level is reported higher than the one used; an act below policy's floor takes effect; or the count of acts leaves out an act that should exist. The model in `spec/intent/` covers these for exceptions only, with three of the six levels.
