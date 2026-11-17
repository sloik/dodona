# The conformance kit and the first seed kernel

Date: 2026-11-17.

## Order of events

1. The conformance kit, version 0, was written and committed: 27 scenarios and the encoding and path vectors. No kernel existed.
2. A decision record said what the first seed would be and what it could claim ([0025](../../decisions/0025-the-first-seed-kernel.md)).
3. The seed was written by Codex, a different make of AI model from the one that wrote the documents and the kit. It was given the documents, the kit and the two judging tools, and told not to read the reference path check or the formal models.
4. The author of the kit then built the seed, ran both judges, read every line of the two decision modules, and planted defects.

## What was found

- The seed passed all 27 scenarios and all 25 encoding vectors at the first attempt. Its author reported no disagreement between the kit and the documents.
- It is 650 lines of Rust with no third-party packages and no `unsafe`. It does not read the scenarios' expected answers.
- **15 defects were planted in it, one at a time: each defect the formal models plant, and one more. The kit rejected all 15.** This is now a permanent check, `tools/kit_adequacy.py`.
- One ambiguity in the kit's contract: when attempts overlap, "the most recent attempt" does not say whether that means submitted last or finished last. The seed uses submission order. No scenario separates the two readings yet.
- The contract does not say what a kernel should do with a malformed scenario.

## What this does and does not show

It shows that a kernel written independently from the documents agrees with hand-written expectations on 27 scenarios, and that the kit is strong enough to reject the defects it was designed around.

It does not show the seed is correct. The scenarios sample behaviour; they do not cover it. A first-attempt pass by a capable model on a small, well-specified task is weak evidence that the kit is hard to pass. The defects planted were ones somebody thought of. And the two makes of model may share blind spots.

## The schema drafts

In parallel, a separate agent drafted the message, lock, policy and status schemas, a configuration reference and a provider guide, from the documents alone, and validated every example in the guide against its own schemas. It reported eight contradictions or gaps in the existing documents. Those resolved so far: what an intent's identity covers and who works it out; time limits being lengths of time, not dates, so no clock enters an identity; a build record carrying no strength; and policy living in its own file. Still open: where the lock is stored and in what format, and which statement of a tool's requirements wins when the configuration, a provider and the resolver disagree.

The schemas have not been reviewed by anyone but their author and a structural check.
