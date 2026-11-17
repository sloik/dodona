# Intents

What dodona is meant to do, in plain words. This directory is dodona used on itself before dodona exists: the intents are real, and until a kernel can derive their status it is worked out by hand and stated honestly.

Each intent has an owner, criteria, and for each criterion a gate ([data model](../MODEL.md#5-intent-gates-and-assurance)). Children can be worked on in parallel where they touch different things.

| Id | Intent | Parent | Status today |
|---|---|---|---|
| [0001](0001-dodona.md) | An agent can find out whether what was defined was built and delivered, and how sure that is | | open |
| [0002](0002-kernel-design-is-checked.md) | The kernel's rules are checked before any kernel is written | 0001 | open |
| [0003](0003-a-provider-can-be-written-from-the-documents.md) | Someone outside can write a provider from the documents alone | 0001 | uncovered |
| [0004](0004-same-answers-on-every-platform.md) | The same project gives the same answers on every platform | 0001 | uncovered |
| [0005](0005-a-kernel-can-be-judged.md) | A kernel can be judged by something that is not a kernel | 0001 | uncovered |
| [0006](0006-intent-to-delivery-is-traceable.md) | The path from an intent to what was delivered can be traced and scored | 0001 | uncovered |

`uncovered` means at least one criterion has nothing that checks it yet. That is the honest state of a project at design stage.
