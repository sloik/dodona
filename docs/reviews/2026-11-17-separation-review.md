# Review of the separation scale

Date: 2026-11-17. [Decision 0024](../../decisions/0024-separation-is-graded-not-enforced.md) was reviewed by one AI agent playing an orchestrating agent under pressure to ship, wanting the highest level for the least effort without doing anything it would call lying.

## The central finding

**A worker acting alone could reach `cross-make`, the fifth level of six, with every fact resting on its own word.** It calls itself the owner and its sub-agent the worker, writes the brief itself, leaves out the field that says who started the checker, supplies its own known-bad case, names its own script a different make, and takes a ticket only for the attempt that agreed. The default policy accepted declared facts. The most flattering headline it could truthfully produce was `separation: cross-make (declared), 4 of 4 acts apart or better`, for work no independent party had looked at.

## What changed

| Finding | Change |
|---|---|
| Every level up to `cross-make` reachable by declaration | A claim is not a grade. Declared facts earn `helper` at most; higher needs an attestation; shown as `helper (claims apart)`. Today the highest grade is `helper` |
| The rule from record to level was not written down, and the kit took the level as given | A table of the facts each level needs. The kit and the model are being changed to take claims with their source |
| The default policy accepted all of it | Confirmation now needs `helper`. The floors at `apart` cannot be met yet, so no exception takes effect for now, and the policy file says so |
| The worker could supply a trivial known-bad case and tell the checker which it was | A known-wrong and a known-right case, supplied by the owner or taken from the check's planted defects, bound to the criterion, given unlabelled |
| Retrying until agreement left no trace: change the work trivially, or ticket only the winner | Attempts are counted along the line of the criterion, not by content. The count is in the headline |
| A script could be named a "different make" | A deterministic tool is not a make. Makes are compared by a list in policy |
| The worker chose which acts to report, so "4 of 4" | The kernel works out which acts there must be. A missing act is at `self` |
| A record could state how well supported its own facts were | Removed from the record. The kernel works it out |
| A judgement could be packaged as a rerunnable check to avoid grading | Saying a check tests a criterion is graded for every check |
| The cap at `self` could be read as depending on the floor | The cap applies whatever the floor |
| The headline example led with a level higher than its weakest act | Corrected |

## Not closed

- **Nothing can attest.** No harness key exists and policy cannot yet be protected from the agent it constrains, so an agent that could write the list of trusted keys could attest to anything. Until both exist the scale stops at `helper` in practice.
- **Steering through the work itself.** A comment planted in the thing being judged cannot be told from content.
- **Attempts made without a ticket** leave no trace. They cannot earn a level and cannot be counted.
- **The model covers three levels and one kind of act** (exceptions). The other acts and levels are not modelled.
- **Separation is not competence.** Two checkers of similar make share blind spots.
