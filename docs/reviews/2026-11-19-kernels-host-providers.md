# Reviews of the first step of decision 0033: both kernels host providers

Date: 2026-11-19. Each kernel gained a `session` and a `check` command, written by its own author in a fresh context, against a contract and a kit written by someone else ([decision 0033](../../decisions/0033-a-kernel-hosts-providers.md)). The contract went through four rounds. After each round a separate AI agent, in a fresh context, read the contract, the kit, the reference hosts and both kernels and tried to break them. This log records what those readings found and what was done.

## What the rounds changed

| Round | Found by | What changed |
|---|---|---|
| 1 | The first verifier | Shapes of the host's input, the manifest, the run description and the final; strict reading at any depth; the deadline counts against sending; attachments as regular files of at most 64 MiB reached without a link; the process promise narrowed to the process group or job |
| 2 | Both kernels' authors | Renumbered rules; `env` refused whatever its value; outputs compared with the check's inputs ignoring case |
| 3 | The JavaScript kernel's author | The executor in a process group of its own, ended when it returns; its exit status alone ends a check in error; a link at an inner step of an attachment path; what a tool file's segments may hold; the protocol text aligned with host rule 9 |
| 4 | The verifier of the merged kernels | Below |

## Round four: the verifier of the merged kernels

| # | Finding | Done |
|---|---|---|
| 1 | The planted-defect jobs would pass CI's time limit, because every judge ran on every defect | `tools/kit_adequacy.py` and `kernel2/plant.js` stop at the first judge that rejects a defect, the judge meant for the defect's file first |
| 2 | A host that starts nothing can pass every case by writing the judge's records itself | Not fixable while the host starts the programs that keep the records. README, CLAIMS C13 and the kit now say what the judge shows: a host that skips or changes a step is caught, one written to forge the records is not |
| 3 | The judge did not check what a host sends | It now checks the start request's body, each report passed back against what the executor printed, the echo of `hello` and the closing `shutdown` |
| 4 | Contract rules with no case | 29 check cases and 2 session cases added; each goes red on the reference host with its rule removed |
| 5 | A run could use a tool whose digest is never checked | Rule 4 gains `tool-not-in-run` |
| 6 | The two kernels answered differently on a slow executor and on a report ended by CRLF | The wait and the report's reading are written down, with cases |
| 7 | The reference differed from both kernels on ten inputs | Settled in the text, with a case for each (below) |
| 8 | Skipped cases were counted as matched | Reported separately |
| 9 | README case counts were stale | Corrected |
| 10 | C20 said every judge runs on each defect | Corrected |
| 11 | C37's outputs hold only counts, so they do not show which kernel was compared | Said in the record's note |
| 12 | No comparison of the two kernels' `session` and `check` beyond the cases | Recorded under "Not yet in the kit" |
| 13 | Windows process handling: no timeout on the process-table read, a reused pid could be ended, a failed job assignment went unnoticed | Done in each kernel |
| 14 | Few cases for the host's own input | Four added, and one for input that is not JSON |

## How the open choices were settled

Where the contract left a choice open and the three hosts differed, the choice was made from a rule already in the text, never because a kernel did it. Several came out the way both kernels had chosen, and the reference host was changed to match. So that this can be checked, here is each choice with the rule it follows from:

| Choice | Settled as | Follows from |
|---|---|---|
| A manifest with no `tools` | `bad-manifest` | The manifest's `tools` "is a list"; a missing list is not a list, and reading it as empty would let a provider declare nothing and be held to nothing |
| A strength given as `null` | `bad-manifest` | "the strength (where given) an object": `null` is given and is not an object |
| `NaN` or `Infinity` | `malformed`, in a session as in a check | They are not JSON; a session reads JSON as JSON, not as Python's reader extends it |
| A provider that answers and then does not exit after `shutdown` | ended after a second; its answer stands | The answer was complete and every rule was kept before it; ending the process is the host's promise, and a refusal would rest on nothing the provider said |
| The executor's working directory | the project's `root` | `root` "is the directory the provider is started in and paths are relative to"; the run's paths are relative to it, so the executor that runs them starts there |
| The order when two entries break different rules | rule by rule over every entry | The rules are listed "in this order"; reading them entry by entry would make the reason depend on the order of a list the provider chose |
| How long to wait for an executor | at least `wall_ms` plus 60 seconds, at most 24 hours | A host's deadline bounds messages to the provider; a run is bounded by its own limit, and the margin keeps a run that just meets its limit from becoming `timed-out` |
| An executor's report ended by CRLF or after an empty line | no report | "reads one report from standard output, strictly, as messages are read", and a message ends with a line feed alone |
| A final whose verdict is `unavailable` | `bad-verdict` | The verdicts a provider may give are listed, and `unavailable` is not among them: it is what the host concludes from the executor's report |
| Host input that is not an object, or not JSON | `bad-input` | The host's input "must have that shape before anything else is done" |

## What this step does not do

- It does not compare the two kernels' `session` and `check` commands with each other beyond the cases, so an input no case gives may still get two answers.
- It does not judge a host written to forge the records the judge reads.
- Three attachment cases cannot be made on Windows and are skipped there.
- The kernels' Windows process handling is compiled and written, and has run only as far as CI's Windows job exercises it.
- The pipeline and the status command, the second step of decision 0033, are not here.
