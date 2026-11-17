# dodona data model

Status: **draft 0.2**, not implemented. This file defines the terms the [architecture](ARCHITECTURE.md) uses. Field-level schemas live in [protocol/](protocol/README.md).

## 1. Nodes

Every node has a **name** (stable, how it is referred to) and an **identity** (a content hash, how change is detected), except where noted.

| Node | Name | Identity | Comes from |
|---|---|---|---|
| Definition | Path or symbol, scoped by the binding that indexed it | Hash of content, as the language provider defines content | `definition.index`, or the file-level fallback |
| Specification | A definition whose role is to state what must hold | Same as a definition | `definition.index` for the specification language |
| Decision | Its id | Hash of the record | `decision.index` |
| Obligation | Binding name plus a provider-chosen locator | Hash of binding and name. Stable across edits | `obligation.enumerate` |
| Artefact | Producing obligation plus output path | Hash of content | `artifact.build` |
| Tool | Name and version | Hash of the canonical tree listing | `tool.resolve` |
| Record | None | Hash of its canonical encoding | The kernel |
| Policy | None | Hash of the policy file | The project owner |

A specification is not a different kind of thing from a definition. Specifications are indexed, hashed and depended on like any other definition; the word names a role in an obligation.

## 2. Edges

| Edge | From → to | Meaning |
|---|---|---|
| `depends-on` | Definition → definition | Changing the target can change the meaning of the source |
| `governs` | Decision → definition name | The decision constrains this definition; records the identity at the time of writing |
| `supersedes` | Decision → decision | The older decision no longer applies |
| `specified-by` | Obligation → definitions | The specification side of an obligation |
| `targets` | Obligation → definitions or artefacts | What is being checked |
| `produced-by` | Artefact → obligation | The build that produced it |
| `requires` | Tool → tool | A tool that needs another to run |
| `evidences` | Record → obligation | A check that ran |

The **closure** of a definition is everything reachable from it over `depends-on`. An obligation's inputs are the closures of everything it is `specified-by` and `targets`, plus for each artefact the inputs of the obligation that produced it.

## 3. Obligations

An obligation is one question with a yes or no answer: *do these targets satisfy this specification, as judged by this provider with this configuration?*

Obligations are **enumerated by the verifier or conformance provider**, not invented by the kernel, because only the provider knows what its tool can check separately: one model with one configuration, one lemma, one test. The kernel asks each binding for its obligations and receives, for each:

| Field | Meaning |
|---|---|
| `name` | Stable locator within the binding. Survives edits to the content |
| `specified_by`, `targets` | Definition or artefact names |
| `kind` | `check`, `build`, `conformance` or `reproducibility` |
| `expect` | `holds` or `violated` |
| `defect_of` | For a planted defect: the obligation whose check it must break |
| `config` | Bounds, flags, seeds, worker counts and limits |

**Planted defects are obligations.** An obligation with `expect: violated` passes when the checker finds the violation it names. Its `defect_of` field ties it to the obligation it guards. This is how dodona's own rule, that a check must be shown able to fail, becomes something the kernel tracks instead of a habit.

**Build is an obligation too.** `artifact.build` produces artefact nodes under an obligation of kind `build`. Anything that consumes the artefact depends on that obligation's inputs, so changing the compiler invalidates the tests of what it compiled.

## 4. Status

A **run** ends in one of six verdicts, defined in [the architecture](ARCHITECTURE.md#5-verdicts-status-and-evidence). Status is what the kernel derives from the ledger.

**Obligation status**

| Status | Rule |
|---|---|
| `passed` | At least one reusable record for the current key, all of them `passed` |
| `failed` | At least one reusable record for the current key, all of them `failed` |
| `conflict` | Reusable records for the current key disagree |
| `unknown` | No reusable record for the current key. Carries a reason: `never-run`, `pending`, `unavailable`, `error`, `unsupported` |

Each status also reports:

- `evidence_class`: the weakest class among the records it rests on
- `non_vacuous`: `shown` if every planted defect of this obligation is itself `passed`, `not-shown` if any is not, `none-planted` if there are none
- `trusted_base`: the union of the kernel's, the provider's and the records' assumptions
- `isolation`: the weakest isolation level among the runs

A rerun never replaces a record. It adds one, and disagreement becomes `conflict`. A conflict is cleared only by a change of inputs or by an explicit, recorded decision to retire named records.

**Project status** is relative to the policy in force:

| Status | Rule |
|---|---|
| `passed` | Policy requires at least one obligation, and every required obligation is `passed` at or above the required evidence class, non-vacuity and isolation |
| `failed` | At least one required obligation is `failed` or `conflict` |
| `unknown` | Otherwise, with the list of obligations that are not yet decided |
| `nothing-required` | Policy requires no obligation. Never shown as a pass |

The result also names the policy identity it was judged against, and whether that policy differs from the reference policy ([decision 0014](decisions/0014-policy-is-separate-from-configuration.md)).

## 5. Trusted base

One list, referred to from everywhere else. Every status reports the subset it rests on.

Assumed by the kernel's design:

1. A provider's verdict is correct for the inputs it was given.
2. A provider declares every input its result depends on.
3. Equal identities mean equal content.
4. The input copy handed to a run is not altered while the run uses it.
5. The executor ran the tools it reported, on the platform it reported.
6. The ledger keeps what was written and does not alter it.
7. The kernel itself, and the seed it was built from, behave as specified.
8. Each pinned tool is what its upstream published.
9. The specification states the property that was actually intended.
10. Whoever can change policy is authorised to.

Declared by each provider in its manifest, for example: the model checker is correct, the language runtime under it is correct, the foreign-function shell is not covered by the proof.

Reported per record, for example: this proof used these axioms; this run was not isolated.

Assumptions 1, 2 and 5 are not left as pure trust. The conformance kit perturbs a provider's environment to look for undeclared inputs, the executor's report is compared with the lock, and a second platform or a second run can expose a wrong verdict as a conflict. None of that removes the assumption; it makes violations more likely to be seen.

## 6. Agent interface

A sketch, to be replaced by schemas. Every command takes and returns structured data, never prompts, and can be run repeatedly with the same result. A command never waits for a long check; it returns and can be asked again.

| Command | Does | Returns |
|---|---|---|
| `resolve` | Reads configuration, produces or verifies the lock | Lock identity, anything unresolvable per platform |
| `index` | Asks providers for definitions, decisions and obligations | Graph summary and every rejected path or file with a reason code |
| `status` | Derives status from the graph and ledger | Project status, and per obligation: status, reason, evidence class, non-vacuity |
| `plan` | Works out what is stale | Ordered obligations to run, each with why it is stale |
| `run` | Submits planned obligations to executors | Run handles; verdicts for anything that finished |
| `explain` | Traces one result | Its key structure, records, trusted base, and the decisions governing its targets |
| `review` | Lists decisions whose governed definitions changed | Decision, name, old and new identity |
| `reproduce` | Compares records with one core key across platforms | Agreement, disagreement or `unknown` per obligation |

Errors carry a stable code, the node concerned, and no information that exists only as prose.
