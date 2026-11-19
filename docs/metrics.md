# Metrics

How complete the project is and how much of it is checked, as numbers, with the change on every pull request and every push to `main`.

`tools/metrics.py` counts what files in this repository state. Every number names the file it comes from, so a reader can open that file and count again. The tool runs no kernel, no model and no checker. A number says what a file states, not that the statement is true: a claim marked checked in `spec/CLAIMS.md` is counted as marked checked, and whether the mark is honest is what `tools/check_repo.py` and the recorded runs are for.

```
python tools/metrics.py                    the numbers, as a table
python tools/metrics.py --json             the numbers, as JSON
python tools/metrics.py --compare FILE     the change against an earlier --json output
python tools/metrics.py self-test          plants changes and requires each to be judged right
```

`--compare` exits 1 when a ratcheted number went down without a waiver, and 2 when something could not be measured or the earlier file could not be read. A file that is missing, or that does not read the way the tool expects (a heading renamed, a claim with a status it does not know, a claim marked checked by a run that is not recorded), stops the tool. It is never counted as zero.

## What is measured

| Metric | Source | Rule |
|---|---|---|
| `kit.scenarios` | `conformance/kernel/*/*.json` | ratcheted |
| `kit.scenarios.<kind>` | `conformance/kernel/<kind>/*.json` | shown |
| `kit.vectors` | every top-level list in `conformance/vectors/*.json` | ratcheted |
| `kit.vectors.<file>` | every top-level list in that file | shown |
| `kit.ledger_cases` | `conformance/ledger/cases.json` (`append`, `damage`) and `more-damage.json` (`damage`, `bad_requests`, `unlisted_kind`) | ratcheted |
| `kit.host_check_cases` | `cases` in `conformance/provider/check-cases.json` | ratcheted |
| `kit.session_cases` | `cases` in `conformance/provider/cases.json` | ratcheted |
| `planted_defects.kernel`, `planted_defects.kernel2` | `defects` in `kernel/defects.json` and `kernel2/defects.json` | ratcheted |
| `claims.total` | rows `\| C<n> \|` in `spec/CLAIMS.md` | ratcheted |
| `claims.checked` | claims whose status is `**checked**, run <n>`, with run `<n>` under Recorded runs | ratcheted |
| `claims.unchecked` | every other claim | shown |
| `claims.sampled_by_kit`, `claims.modelled_unchecked`, `claims.not_modelled` | the other statuses, and the section "Not yet modelled" | shown |
| `decisions.total` | `decisions/[0-9]*.md` | ratcheted |
| `decisions.<status>` | the `status:` of each record | shown |
| `gaps.not_in_kit` | bullets under "Not yet in the kit" in `conformance/README.md` | shown |
| `gaps.gap_checks` | rows of the "Check" table in `docs/gap-checks.md` | ratcheted |
| `gaps.tool_checks` | rows of the "Tool" table in `docs/gap-checks.md` | ratcheted |

The planted defects are counted only. The count is not what a kernel is judged by; `tools/kit_adequacy.py` and `kernel2/plant.js` do that.

Some counts differ from those in the README, because they count different things. `kit.vectors` includes `tool-tree.json`, which no kernel is judged with; the README's encoding, path and key vectors are the other four files. `kit.ledger_cases` counts the cases the two ledger files list. The README's ledger checks are what `tools/run_ledger_cases.py` checks when it runs, including a cut at every byte, which no file lists.

Open GitHub issues are not measured: they are not a file in the repository.

## Why these are ratcheted and those are shown

A ratcheted number may only go up. It is a number where going down means something that judged the project, or something the project said about itself, was taken away: a scenario, a vector, a ledger or host case, a planted defect, a claim, a decision record, a gap check, or a claim's checked mark. Taking any of these away weakens a check or hides a statement, which [AGENTS.md](../AGENTS.md) rule 7 forbids unless it is said out loud.

A number that is only shown can move either way as the project grows. The unchecked claims fall when a claim is checked and rise when one is added. The items not yet in the kit fall when an item is added to the kit and rise when a gap is found. The decisions by status move when the owner accepts or supersedes a record. The breakdowns by kind and by file move when an item is moved from one file to another; their totals are ratcheted.

A metric that was ratcheted and is gone, or is no longer ratcheted, counts as having gone down. Taking a ratchet away is a weakening too.

## When a number goes down on purpose

A number may go down for a good reason: a scenario removed because it judged a rule the contract no longer has, or a claim un-checked because its model changed and the run that checked it no longer matches (`tools/check_repo.py` requires this). The one way to allow it is a line in the message of a commit in the change:

```
Metrics-down: kit.scenarios: the scenario judged a rule the contract dropped
```

The line starts with `Metrics-down:`, names one metric exactly, and gives a reason of at least six words. One line allows one metric to go down in that change, by any amount. A line that names no metric, names one that does not exist, gives a shorter reason, or nearly has the right form (`metrics-down:`, `Metrics down:`) allows nothing and is listed in the summary as refused. A waiver for a number that did not go down is listed too.

The commits read are the same for a pull request and for a push: every commit reachable from what is being measured and not from the commit the earlier metrics were measured on. A waiver therefore stays visible in the history and in the review. A squash merge keeps it when the squashed message keeps the commit messages. If a push to `main` fails the ratchet, the run is not successful and its metrics are not used. The next push is compared with the same earlier metrics and must carry the waiver, or put the number back.

## In CI

[`.github/workflows/metrics.yml`](../.github/workflows/metrics.yml) runs on every pull request and every push to `main`. It runs the self-test on macOS, Linux and Windows. It measures, and on a push to `main` it keeps the JSON as an artifact. It fetches the metrics kept by the last successful run of a push to this repository's `main`, the way the model checks fetch their ledger, compares, and writes the table and the changes to the job summary. If no earlier metrics exist (the workflow is not on `main` yet, no run there has succeeded, or what it kept has expired), the summary says so, shows the numbers, and judges nothing. A lookup that fails is a failure, not "nothing to compare".

## The self-test

`python tools/metrics.py self-test` copies the source files to a temporary folder, plants one change at a time, and runs the tool's own command line on each, requiring the stated exit code and, for a ratchet, that the row of that metric is the one that fails. It plants:

- nothing changed, a scenario added, an item of "Not yet in the kit" removed and a decision accepted, which must all pass;
- a scenario removed, with no waiver, a valid waiver, a waiver among other commit text, a reason of five words, no reason, a waiver for another metric, one for a metric that does not exist and one with the key misspelt: only the two valid waivers pass;
- a claim un-checked, with and without a waiver;
- a planted defect removed from each kernel, a vector, a ledger case, a host case and a session case removed, a gap check, a decision record and a claim taken out of their lists;
- the same drop and a waiver whose reason holds `|` and a backtick, with the Markdown output CI uses;
- sources that cannot be read: a heading renamed, a claim checked by a run that is not recorded, unknown statuses, a file that is not JSON, one that is not UTF-8, a vectors file whose name cannot be a metric, and earlier files that are malformed. Each must exit 2; a crash is exit 2 too, never 1;
- for every ratcheted metric, an earlier value one higher, which must fail on that metric's row, and for every shown metric the same, which must pass;
- a ratcheted metric that is gone, with and without a waiver, a shown metric that is gone, and a ratchet taken away.
