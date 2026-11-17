# Review of the protocol schemas

Date: 2026-11-17. The schemas under `protocol/` were reviewed by one AI agent acting as two people: someone writing a provider for a real tool (a prover that also compiles, and a plain test runner) from the repository alone, and someone writing the kernel side who must never let a wrong message become a pass.

## What held

Every schema is valid, every reference resolves, every example in the provider guide validates against the message schema, and dodona's own policy file validates against the policy schema. The reviewer wrote complete, valid message sequences for both tools.

## What did not

The schemas were mechanically sound and far too permissive. Of 18 messages that are wrong in a way that matters, the schemas alone refused 4.

| Finding | Change |
|---|---|
| The evidence key could not be recomputed: the documents said it covers the provider and its version, and the record said "hash of inputs" | The exact hashed object is now defined in the record schema, with the kind of record and, for conformance, the mapping files |
| A final "passed" with no run behind it was accepted | Refused by rule: a verdict rests on at least one run |
| A run's result did not say which check it belonged to, and a repeated run could be answered from an earlier one | The result names its check and its run number; each run has its own key |
| Two documents disagreed on who interprets a run that did not exit cleanly | One rule: a run that exits is the provider's to interpret; one that did not exit ends the check in error |
| A program had no environment, so most real tools could not start | A complete, explicit environment, with the tool tree and working directory nameable |
| A provider could report an intent as confirmed, and an exception with an empty grantor | A provider cannot confirm or grant. Those come only from act records |
| A test runner could claim the strongest rank | The rank in the manifest is a ceiling |
| The schema's path pattern let through 29 of 45 refused path vectors | The path check is required on every path; the pattern is only a first filter |
| Sets were sorted one way in three documents and another way in the encoding | One rule, the encoding's |
| Numbers that the encoding refuses were accepted on the wire | Wire parsing is as strict as the encoding |
| A project could be reported as passed with nothing required | Stated as a kernel rule |

These are in [`protocol/README.md`](../../protocol/README.md) under "Rules a schema cannot express".

## Open

A provider for a prover that also compiles **cannot be written from these documents yet**. A single-run verifier can.

- Listing obligations or definitions cannot use a tool, so a provider must carry its own parser.
- A run can declare only named output files, not a directory of them, and how an artifact is named is not defined.
- How a tool tree is listed and hashed is not defined, nor where a provider itself is fetched from, nor how a provider that needs an interpreter is started.
- There is no way for policy to say which assumptions inside a proof are acceptable, so a provider cannot tell whether a proof that assumes something has passed.
- Policy has one minimum strength for everything; proofs and tests cannot be required differently.
- A provider cannot be told its time budget, and policy cannot cap the time a run asks for.
- What a provider does about a planted defect that needs a changed source file.
- The three statements of what a tool requires (configuration, provider, resolver) are not reconciled.
- Whether the C library is part of a platform when it is not given.
- None of this has been exercised: no kernel runs providers yet. The reference host checks message envelopes, not bodies.
