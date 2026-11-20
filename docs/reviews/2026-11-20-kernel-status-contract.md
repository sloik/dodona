# Reviews of the status contract: a kernel reports a project's status (decision 0034)

Date: 2026-11-20. Before either kernel's author sees it, the contract for a kernel's `status` command (conformance/README.md, "How a project's status is judged"), its reference (`tools/project_status.py`) and its cases (`conformance/project/`) were attacked, each time by a separate AI agent in a fresh context that had not written them. Each attack planted faults in copies of the reference and looked for a status command that reports a project better than it is and still matches every case. This log records what each found and what was done.

## What the attacks found

| Attack | Wrong passes found | Planted faults that matched every case | What changed |
|---|---|---|---|
| 1 | A policy whose required intents were text turned a failed project into nothing-required; a criterion id given twice hid a hard gate | 24 of 46 | The input's policy, code paths and ledger paths checked; strict reading of the input; one grammar for patterns; a provider must be the one its binding names; answers checked rule by rule; intents checked whole, with duplicate criteria, unknown links, two parents and cycles refused; acts only from the owner's ledger; coverage with one root per intent. 49 cases became 95 |
| 2 | A misspelt policy field, or one the command never read, turned unknown into passed; a command skipping the ledger's checks matched every case | 81 of 157 | The policy closed to the fields of its schema; the ledger kit's damaged ledgers made status cases; junctions treated as links; unreadable folders and files refused; generated variants: every field of the answers, policy and input taken away or retyped, each project-file line edited a dozen ways, the reference's answer required. 132 cases |
| 3 | The owner's ledger read without its checks; the policy closed only where cases looked; provider messages never malformed; manifest strings never varied; a project stated passed although its policy held fields no rule applies | most of the remaining survivors were missed by plain cases and variants alike | The site checks the policy against its schema and hands over only what the status rules apply, with every other field named (`tools/policy_input.py`); the command states a project unknown, never passed or nothing-required, while any is left; the owner's ledger tested with every damaged ledger, an edited act and a missing last line feed; the fixture provider sends raw lines; a manifest's protocol must be the one offered. 176 cases and about 5,700 generated variants |
| 4 | A required intent's descendants never applied, so a failed child left the project stated passed; an obligation the provider could not make into a check dropped silently; a floor of 0 read two ways | 22 of 64, mostly orderings, empty names and session reasons no case sent | The command states a project unknown while anything could hide a failure (policy not applied, children of a required intent, obligations nobody can check, a torn ledger), each named in `project_doubts`; the floor handed over as at least 1; `reference` named as not applied and an unknown policy version refused; a link to nothing, a code path twice, empty names and paths refused; UTF-16 order, .git and linked folders, deadlines, and every strict-reading reason given a case; the judge reads answers strictly, requires exactly the fields and exit 0. 198 cases |

## Settled by a rule, not by a case alone

Where the text was silent, the choice was made from a rule already written, and the text now says it:

| Choice | Settled as | Follows from |
|---|---|---|
| A policy field nobody applies | named in `policy_not_applied`; the project is stated unknown while any is left | "Only a pass is a pass": a field nobody applied could have failed the project |
| Who checks the policy against its schema | the site, which anchors the policy anyway | A kernel names no format; the site already decides where the policy comes from |
| A ledger whose path is spelt otherwise, or a hard link to one already read | read once | The same file is the same record; reading it twice would count its results twice |
| A folder or file under the root that cannot be read | `unreadable-file` | A status read from part of the files would look whole, as for an unreadable intent |
| A provider command that cannot start | `provider-not-started` | A refusal names its reason; a crash is never an answer |
| On a refusal, which providers were started | exactly those the reference starts, asked the same | "nothing after the broken rule is done" |

## What this does not do

- It judges the status command only. The `run` command, which plans, sends batches to the site's executor and records verdicts, has no contract yet.
- Statuses are written by hand only in the cases that name them; the rest of each report is compared with the reference's view and recomputed with a kernel's `scenario` command.
- A provider's processes, the per-message deadline and the line limit are judged in the host checks, not again here; a provider started elsewhere than the project root is not detected.
- The two kernels' status commands are not yet compared with each other on inputs no case gives.
- No status rule reads a deferred gate's limit, `required.obligations`, a least strength, the match-check floor or a required intent's descendants yet; a project with any of them is stated unknown, never passed. dodona's own intents hang off one required intent with children, so dodona's own status reads unknown until descendants are read.
- What remains from the fourth attack and is written down rather than closed: a provider's processes and its working directory are judged in the host checks only; whether the `--kernel` given the judge is another kernel is the caller's to ensure.
