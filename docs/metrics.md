# Metrics

How complete the project is and how much of it is checked, in numbers, and which of them may only go up.

`tools/metrics.py` counts what files in this repository state. Every number names the file it comes from, so a reader can open that file and count again. The tool runs no kernel, no model and no checker. A number says what a file states, not that the statement is true. For example, a claim marked checked in `spec/CLAIMS.md` is counted as marked checked; whether the mark is earned is for `tools/check_repo.py` and the recorded runs to show.

```
python tools/metrics.py                        the numbers, as a table
python tools/metrics.py --json                 the numbers, as JSON
python tools/metrics.py --base REV --head REV  what a change took away, read from git objects
python tools/metrics.py self-test              plants changes and requires each to be judged right
```

`python tools/metrics.py --help` lists the rest. The exit code is 0 when nothing ratcheted was taken away, 1 when something was, and 2 when something could not be measured. A file that is missing, or that does not read the way the tool expects, stops the tool with exit 2 and is never counted as zero. Examples: a renamed heading, a stray line in a list, a claim with an unknown status, a claim marked checked by a run that is not recorded, or two items with the same identity.

CI shows the numbers and what changed on each pull request and each push to `main`. The run fails when a ratcheted item was taken away. That stops a merge only where `main`'s rules require the check; elsewhere it only reports.

## What is measured

| Metric | Source | Rule, and what an item is |
|---|---|---|
| `kit.scenarios` | `conformance/kernel/<kind>/<name>.json` | ratcheted, by kind and name |
| `kit.scenarios.<kind>` | the same, one kind | shown |
| `kit.vectors` | `accept`, `reject`, `reject_bytes` and `collisions` in `conformance/vectors/` `canonical.json`, `core-key.json`, `core-key-more.json` and `paths.json`: the vectors the kernels are judged with | ratcheted, by name, or by the path or bytes where a vector has no name |
| `kit.tool_tree_vectors` | `conformance/vectors/tool-tree.json`, judged against the reference only | ratcheted, by name |
| `kit.vectors.<file>` | one vector file | shown |
| `kit.ledger_listed_cases` | the cases the ledger files list: `append` and `damage` in `conformance/ledger/cases.json`; `damage`, `bad_requests` and `unlisted_kind` in `more-damage.json` | ratcheted, by name; the appends and the unlisted kind are counted |
| `kit.host_check_cases` | `cases` in `conformance/provider/check-cases.json` | ratcheted, counted: two cases share a mode, so a case has no identity |
| `kit.session_cases` | `cases` in `conformance/provider/cases.json` | ratcheted, by mode |
| `planted_defects.kernel`, `planted_defects.kernel2` | `defects` in `kernel/defects.json` and `kernel2/defects.json` | ratcheted, by name |
| `claims.total` | rows `\| C<n> \|` in `spec/CLAIMS.md` | ratcheted, by claim id |
| `claims.checked` | claims whose status is `**checked**, run <n>`, with run `<n>` under Recorded runs | ratcheted, by claim id |
| `claims.unchecked` | every other claim | shown |
| `claims.sampled_by_kit`, `claims.modelled_unchecked`, `claims.not_modelled` | the other statuses, and the section "Not yet modelled" | shown |
| `decisions.total` | `decisions/[0-9]*.md` | ratcheted, by file name |
| `decisions.<status>` | the `status:` line of each record | shown |
| `gaps.not_in_kit` | the `- ` items under "Not yet in the kit" in `conformance/README.md`; any other line there is unreadable | shown |
| `gaps.gap_checks` | the "Check" table in `docs/gap-checks.md`; each must be an entry of `GAP_CHECKS` in `tools/check_repo.py`, read from its source | ratcheted, by check name |
| `gaps.tool_checks` | the "Tool" table in `docs/gap-checks.md` | ratcheted, by its first cell |

The planted-defect lists are counted only. A kernel is judged by planting the defects (`tools/kit_adequacy.py`, `kernel2/plant.js`), not by this count.

`kit.vectors` counts the same 119 vectors as the README. `kit.ledger_listed_cases` is the 46 cases the two files list. It is not the README's 89 ledger checks, which are what `tools/run_ledger_cases.py` makes of those cases when it runs, including a cut at every byte.

Open GitHub issues are not measured, because they are not a file in the repository.

## Ratcheted and shown

A ratcheted metric is a set of items, each with its identity where it has one. A change fails when it takes any item away, even if it adds another, so renaming or replacing an item counts as taking one away. Where items have no identity, the count must not fall. These metrics hold what judges the project, or what the project says about itself. Taking an item away weakens a check or hides a statement, which [AGENTS.md](../AGENTS.md) rule 7 forbids unless the owner agrees.

A shown metric can move either way as the project grows:

- the unchecked claims fall when a claim is checked and rise when one is added;
- the items not yet in the kit fall when one is added to the kit and rise when a gap is found;
- the decisions by status change when the owner accepts or supersedes a record;
- the breakdowns by kind and by file change when an item moves between files, and their totals are ratcheted.

A ratcheted metric that disappears, or stops being ratcheted, counts as taking its items away.

## When an item is taken away on purpose

Some removals are right. A scenario may judge a rule the contract no longer has. A claim must lose its checked mark when its model changes and the run that checked it no longer matches, and `tools/check_repo.py` requires that. The change still fails. Its author explains it with a line in a commit message of the change:

```
Metrics-down: kit.scenarios: the scenario judged a rule the contract dropped
```

The line starts with `Metrics-down:`, names one metric exactly and gives a reason of at least six words. The report shows it next to the failure, for the owner, and the owner decides whether to merge over the failure. The line does not make the change pass, and nobody can grant that to their own change. The report also lists lines that are not well-formed explanations (a wrong key, an unknown metric, a reason that is too short) and explanations for a metric that lost nothing.

Each change is compared with its own base, so a removal that the owner merged over does not carry forward to the next change.

## The self-test

`python tools/metrics.py self-test` works on copies of the source files in a temporary folder, on a scratch git repository and on faulty copies of the tool itself. For each, it requires the stated exit code and, where something is taken away, that the row of that metric is the one that fails. It checks:

- that the ratcheted metrics are exactly the expected list, which is kept apart from the code that measures;
- controls that must pass: nothing changed, an item added, a shown number lowered;
- every ratcheted list taken from in turn: a scenario from each kind, an item from every vector list, ledger list, case list and defect list, a claim, a checked mark, a decision record, a gap check and a tool check;
- a scenario renamed, which takes one away although the count is unchanged;
- explanations that are well formed, too short, empty, for another metric, for no metric or with a misspelt key, each shown and none passing the change, in text and in Markdown;
- sources that cannot be read, each of which must exit 2:
  - a renamed heading, a stray line or a heading under "Not yet in the kit";
  - unknown statuses, and a run that is not recorded;
  - duplicate identities, unknown vector files or lists, and names that cannot be metrics;
  - a listed gap check that `GAP_CHECKS` lacks, and a `tools/check_repo.py` that does not parse;
  - files that are not JSON or not UTF-8, a link in place of a file, earlier files that are malformed, and an unexpected exception;
- for every ratcheted metric and each of its groups, an earlier state with one item more, which must fail, and for every shown metric an earlier number one higher, which must pass;
- that no other workflow of a change may use the gate's job name;
- that the gate workflow is safe, with each unsafe edit planted and noticed;
- that each planted fault in the tool makes its own self-test fail. The faults are: ignoring `bad_requests`, counting only `accept` lists, skipping a kind, removing a ratchet, comparing counts instead of identities, letting an explanation pass a change, accepting duplicates or stray lines, not looking listed checks up in `GAP_CHECKS`, a crash reading as exit 1, and a workflow guard that misses Python run without `-I`.
