# Intents

What dodona is meant to do, in plain words. This directory is dodona used on itself before dodona exists: the intents are real, and until a kernel can derive their status it is worked out by hand and stated honestly.

Each intent has an owner, the worker whose work it judges, criteria, and for each criterion a gate ([data model](../MODEL.md#5-intent-gates-and-assurance)). Children can be worked on in parallel where they touch different things.

| Id | Intent | Parent | Status today (worked out by a seed kernel) |
|---|---|---|---|
| [0001](0001-dodona.md) | An agent can find out whether what was defined was built and delivered, and how sure that is | | draft |
| [0002](0002-kernel-design-is-checked.md) | The kernel's rules are checked before any kernel is written | 0001 | draft |
| [0003](0003-a-provider-can-be-written-from-the-documents.md) | Someone outside can write a provider from the documents alone | 0001 | draft |
| [0004](0004-same-answers-on-every-platform.md) | The same project gives the same answers on every platform | 0001 | draft |
| [0005](0005-a-kernel-can-be-judged.md) | A kernel can be judged by something that is not a kernel | 0001 | draft |
| [0006](0006-intent-to-delivery-is-traceable.md) | The path from an intent to what was delivered can be traced and scored | 0001 | draft |

`draft` means the owner has not confirmed the criteria and gates in a way a kernel can read. Nothing can be delivered before that. The status is no longer worked out by hand: on every change to `main` a seed kernel derives it from a ledger of real results, and the run's summary shows it ([how](../decisions/0026-the-first-host-and-status-are-stage-0-helpers.md)).

Behind `draft`, most criteria are also uncovered in the kernel's eyes. Many are checked by something that runs in CI, as their tables say, but only checks a provider offers as obligations reach the ledger, and so far that is the model checks. Each intent's criteria are kept as one line of JSON in its front matter, with the gate and the name patterns of the checks behind each, and for a deferred gate what is to be observed after delivery and within how many days; the table in the file is written from that line by `tools/intents.py --write`, and the repository checks refuse a file whose table differs or that holds anything else a reader might take for criteria.

The project intent criteria schema describes the decoded JSON in that one line, including criterion IDs written as strings of ASCII digits. The Markdown reader also checks plain text, number spelling, repeated keys, unique criterion IDs and agreement with the displayed table. The provider's `intent.index` result uses a separate wire schema. [Project intent criteria schema](../protocol/project-intent-criteria.schema.json), [Protocol messages](../protocol/messages.schema.json).

Each intent has an issue where work on it is discussed: [0001](https://github.com/sloik/dodona/issues/3), [0002](https://github.com/sloik/dodona/issues/4), [0003](https://github.com/sloik/dodona/issues/5), [0004](https://github.com/sloik/dodona/issues/6), [0005](https://github.com/sloik/dodona/issues/7), [0006](https://github.com/sloik/dodona/issues/8). Current pieces of work carry the [`step` label](https://github.com/sloik/dodona/issues?q=is%3Aissue+label%3Astep).
