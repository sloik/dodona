# Second review: the seven rewritten models

Date: 2026-11-18. The seven models rewritten after [the first review](2026-11-17-newest-models-and-scenarios.md) had been read by nobody but their author. A separate AI agent read them and the claims table as a sceptical formal-methods engineer, from the text alone, with the recorded outputs to hand. It ran no model.

## The short version

The rewrite fixed what the first review named and left the main weakness in place. Of 18 properties, 12 still restate a definition of their own model, 4 have thin content and 2 have real content. Two models still allow something the design text forbids. One phrase of one claim was checked by nothing. The claims table said each section states which properties have content of their own; that was true of one section in seven.

## Findings and what was done

| # | Finding | Done |
|---|---|---|
| 1 | Tree: "delivered only when it is confirmed" is checked by no property. A kernel that delivers an unconfirmed tree passes all four | The claim no longer says it. A property and a planted defect are open |
| 2 | The claims table promised a per-section account of which properties have content, and gave it for one section | Every section now has one |
| 3 | Planner: for checks and builds, key and truth are the same expression, so the properties cannot fail without a planted defect | Said in the section. A model in which truth is independent of the key is open |
| 4 | Platforms: "verified" is global in the model and per key in the design text, so one key's agreement lets another key's single record stand in | Said in the section as a contradiction, not a weakness. Open: make it per key or change the design text |
| 5 | Tree with a floor of two: a child with one hard gate counts as delivered, which the data model appears to forbid | Said in the section. Open: decide whether the floor applies to children |
| 6 | Attempts: the cap never lowers an accepted agreement; changing the target avoids it. The data model and decision 0024 disagree here | Said in the section and the claim. Open: settle the two texts |
| 7 | Planner: the defect for a tool change also drops the sources, and its recorded failure is for an edit | Said. A defect that drops only the tool is open |
| 8 | Attempts: the "retried" half of the history property has no defect | Said. Open |
| 9 | Platforms: the override defect is two defects at once | Said. Open |
| 10 | Planner: the depth bound leaves every behaviour of seven or more steps unexplored; the bounds text miscounted the definitions | The count is corrected. Given finding 3 the bound hides little |
| 11 | Six wrong behaviours that every property accepts, because properties check one direction only | Listed in the sections. Defects for the other direction are open |
| 12 | Liveness: "every obligation" for a model of one; fairness stronger than the assumption as stated | Reworded |
| 13 | Platforms: one record per key and platform, so a platform disagreeing with itself cannot occur | Said |
| 14 | Two headings named "Run 7"; `expected.json` is not among the files a recorded run is tied to, so what a case is expected to show could change under a "checked" status | Heading renamed. The second is open |

The reviewer also confirmed: no planted defect fails for a type error or an unrelated reason, the settings that switch off deadlock checking hide nothing, and the current model files are the ones the recorded runs name.

## The properties, one by one

| Property | Model | Verdict | Reason |
|---|---|---|---|
| `NoWrongReuse` | Planner | restates; thin content on the test path | Key and truth share one expression; only the store lookup is independent |
| `NoNeedlessRerun` | Planner | restates | The converse of the same identity |
| `WeakestLink` | Assurance | restates | The shown level is defined as the minimum |
| `NotUnderstated` | Assurance | restates | Compares a value with itself |
| `NonVacuitySound` | Assurance | restates | The definition of "shown", in one direction |
| `TreeSound` | Tree | restates | A consequence of the conditions for reporting delivery |
| `TreeGuarded` | Tree | restates | One of those conditions |
| `TreeComplete` | Tree | restates | Those conditions rewritten |
| `ShapeIsConfirmed` | Tree | own content | Depends on every action voiding the confirmation |
| `WorstCounts` | Attempts | restates | The result's own condition |
| `ShoppingIsCapped` | Attempts | restates | Two definitions unfolded |
| `HistoryIsKept` | Attempts | half own content | The count is real; the "retried" half compares a value with itself |
| `OwnRecordDecides` | Platforms | restates | A stand-in is defined as having no own record |
| `StandInIsEarned` | Platforms | restates | A definition unfolded |
| `StandInIsReported` | Platforms | restates | Two names for one expression |
| `ReproSound` | Platforms | restates | The case split of its own definition, in one direction |
| `FlagIsExact` | Decisions | own content, thin | Comes down to the stored value equalling the reviewed one |
| `EventuallyAnswered` | Liveness | own content, thin | Tests which outcomes are tried again; fairness does the rest |

## What this means for the count

24 of 37 claims are marked checked, the same number as before the first review. The number is honest about what ran: every case of every model completed and matched. It says little about whether the rules are right. The repairs are tracked in [issue 27](https://github.com/sloik/dodona/issues/27), and each needs a run on the shared queue, so none was made here.

## Not covered

- The two older models (evidence reuse and intent delivery) were not read again.
- The conformance kit's newer scenarios were not part of this review; they have [their own](2026-11-18-newer-scenarios.md).
