# Taking part

dodona is public while it is still a design, on purpose: it is cheapest to change now, and outside challenge is wanted. People and agents contribute under the same rules.

## Where things are

- [ARCHITECTURE.md](ARCHITECTURE.md) and [MODEL.md](MODEL.md): the current design. Both are drafts.
- [intents/](intents/README.md): what dodona is meant to do, in plain words, broken into pieces that can be worked on in parallel.
- [decisions/](decisions/README.md): why the design is the way it is. Every record is a proposal until the project owner accepts it.
- [spec/CLAIMS.md](spec/CLAIMS.md): what has actually been checked. Most of it has not.
- [docs/reviews/](docs/reviews/): past review rounds and what was done about each finding.

## Useful ways to help now

- **Break something.** Find a sequence of events in which dodona as designed would report something as delivered that was not. A concrete scenario is worth more than a general concern.
- **Bring a tool.** Try, on paper, to fit a checker, compiler or decision format you know into the provider kinds, and report where it does not fit.
- **Bring a use case.** Describe work you would want judged, and what could not be expressed.
- **Take an open step.** Current pieces of work are [issues labelled `step`](https://github.com/sloik/dodona/issues?q=is%3Aissue+is%3Aopen+label%3Astep), each tied to an intent in [intents/](intents/README.md).

## Rules

1. Open an issue to discuss before large changes.
2. A change of direction is a new decision record with status `proposed`.
3. A claim comes with the check that could show it false, and a planted defect showing the check can fail.
4. Never describe something as verified unless the check ran to completion and the run is recorded.
5. No shell scripts, absolute paths or platform-specific assumptions.
6. Whoever does a piece of work does not approve exceptions to how it is judged.
7. A change to code updates the documents that describe it ([docs/doc-map.toml](docs/doc-map.toml)), or a commit message says why none has to change. A pull request's description says what was verified and what was not. Both are checked ([how](docs/gap-checks.md#a-change-must-bring-its-documents)).

## Before opening a pull request

Identify the documentation rules for the paths you plan to change. Allow for owner review if the patch needs a new binding or changes an existing rule. Run the [documentation preflight](docs/gap-checks.md#check-before-opening-a-pull-request) with the exact PR body you plan to submit.
