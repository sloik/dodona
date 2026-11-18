# Review of the seven newest models and their scenarios

Date: 2026-11-17. Two AI agents reviewed work that had been written and run and never read by anyone looking for holes. One read the seven formal models as a sceptical formal-methods engineer. The other wrote kernels that were wrong on purpose, to find what the conformance kit lets through, and built them to prove it.

## The models

**Most properties restated their own definitions.** Of sixteen properties in seven models, the reviewer found two with content of their own. The rest said, in other words, what the rule they checked already said, and could not fail in the intended design. They caught the planted defects and nothing else.

| Finding | Change |
|---|---|
| The attempts model let a change of target erase every earlier attempt, which the design forbids | Attempts are kept along the line; an agreement after any earlier non-agreement is reported as retried whatever happened to the target. A planted defect hides the history |
| The planner's rule that a test runs only on a current build could be deleted with no property noticing; the truth of a result was a hand copy of its key | Truth is found by following the depends-on relation and, for a test, is the artifact it actually ran on. Builds store artifacts under their key. A planted defect runs the test on whatever was built last |
| "Indirect dependency" was claimed and only a direct one modelled | A chain of three definitions; separate defects for "one level only" and "none" |
| The decisions property was literally the same expression on both sides, and missed a kernel that refreshes its stored value on every edit | What was last reviewed is kept apart from what the kernel stores. Two governed names. Two new planted defects |
| The platforms model never checked the value of a stand-in, let one sample verify a claim for everything, and treated every provider as having made the claim | Three platforms, the provider's claim as an input, properties for the value and for reporting, four new defects. The weak notion of verified is now stated in the claim |
| The liveness claim held only because edits, outages and losses were bounded, and that was listed as a bound, not an assumption; an unsupported obligation was called decided | Five assumptions are stated as assumptions. Errors and "unsupported" are modelled. Two new defects |
| The cap on a shopped act was a label, never applied to a level | The level after the cap is modelled, with a defect in which the cap raises it |
| No property mentioned the floor on hard gates in a tree | Two properties and two defects, with a floor of two |
| No model checked that its variables stayed in range | Each does now |
| Claims worded more strongly than the models support | Reworded. Where a property restates a rule, the claims table says so |

Not changed: the assurance model's properties still restate the rule. It is a pure function, and the table now says what such a model is and is not for.

## The kit

The reviewer found no wrong expected result in the scenarios. It found fourteen wrong kernels that passed all of them, and built them.

**The worst was in the judge.** `tools/run_kit.py` sent each scenario to the kernel whole, expected results included. A three-line program that printed them back passed 51 of 51. The judge now removes the expected results and the notes before the kernel sees anything.

The others were rules exercised with only one value, in only one order, or not at all: dependencies one level deep; running something already current; file identity treated as covering every file; the middle evidence link never the weakest; two levels of the scale never compared; a check that stops passing; hard gates counted only on the root; the floor never anything but one; a ticket that did not name its own attempt; shopping that ignored order; a disagreement elsewhere not withdrawing a stand-in; a list never long enough to need sorting; a flag that stayed set after the content was changed back; a failing soft gate; a separation floor never above the third level.

Each now has a scenario, written by the reviewer and worked out by hand, that the wrong kernel fails. The reviewer also listed where the contract was silent, and those rules are now written down.

## What using it found afterwards

The reviews read the work. These were found by running it, the same day.

| Found by | Finding | Change |
|---|---|---|
| Running status on dodona itself | Every criterion that nothing checks was counted as met, and an unchecked deferred criterion as closed. The first real report said "met: 4 of 4" for an intent with no checks at all | A criterion is met only if it has a check and every one passed. A scenario and two planted defects |
| Comparing the two kernels on reshuffled steps | The contract said nothing about a step that arrives out of turn, such as finishing a run that was never started. One kernel crashed | Every step is valid at any point; the rule for each case is written; a scenario and planted defects |
| Validating a recorded provider session | The first real provider sent three kinds of message its own schemas refused | The schemas and the provider were corrected; recorded sessions are validated in CI |
| The second kernel's author, working from the documents alone | Six places where the contract had to be guessed, among them the shape of the project result and what to sign when a covered field is absent | Written into the contract; those still without a scenario are listed as such |
| The agent that finished the first kernel | A required intent that does not exist let the project pass; unknown gate names counted as deferred; one rule written in up to four places; two planted defects that had never compiled and so had always counted as caught | Fixed. A planted defect that does not build is now reported as broken, not caught |
| Planting defects against the final kit | One planted defect, another platform's record overriding a platform's own, cannot be observed in a kernel: a stand-in is only ever taken when all verdicts for the key agree | Removed from the list. The formal model still has the case |
| The shared model checker | The rewritten planner model was too large to finish within the space a job is allowed | It is now bounded by depth: every behaviour of at most six steps from one starting state |

## A second review

The rewritten models were read again the next day by a separate agent. Most of their properties still restate a rule, and two models still depart from the design text: [second review](2026-11-18-rewritten-models.md).

## What the reviews did not cover

- The scenarios added in response, and the new ones for acts, status and the ledger, were reviewed the next day: [review of the newer scenarios](2026-11-18-newer-scenarios.md). It found a hole in the design of vouching and 72 wrong kernels the kit accepted.
- The planted defects are still chosen by the people who wrote the kit. The reviewer's fourteen were not on the list before.
- The first two models (evidence reuse and intent delivery) were reviewed earlier and not again.
