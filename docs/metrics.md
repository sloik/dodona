# Metrics

Ruff checks the metrics tool with the repository's other Python files. The retained `fnmatch` import has a source-line F401 waiver, so another unused import in the checker fails static analysis.

How complete the project is and how much of it is checked, in numbers, and which of them may only go up.

`tools/metrics.py` counts what files in this repository state. Every number names the file it comes from, so a reader can open that file and count again. The tool runs no kernel, no model and no checker. A number says what a file states, not that the statement is true. For example, a claim marked checked in `spec/CLAIMS.md` is counted as marked checked; whether the mark is earned is for `tools/check_repo.py` and the recorded runs to show.

```
python tools/metrics.py                        # the numbers, as a table
python tools/metrics.py --json                 # the numbers, as JSON
python tools/metrics.py --base REV --head REV  # what a change took away, read from git objects
python tools/metrics.py self-test              # plants changes and requires each to be judged right
```

The tool's docstring shows the rest. The exit code is 0 when nothing ratcheted was taken away, 1 when something was (or, between two commits, when the tool or its workflows changed), and 2 when something could not be measured. A file that is missing, or that does not read the way the tool expects, stops the tool with exit 2 and is never counted as zero. Examples:

- a heading renamed or found twice, or a stray line in a list;
- an HTML comment in a file that is parsed, or a row inside a fenced block;
- a claim with an unknown status, or one marked checked by a run that is not recorded;
- two items with the same identity, or a list or item of a kind the tool does not know;
- a link in place of a file;
- a check list in `tools/check_repo.py` bound twice or changed after it is bound.

CI shows the numbers and what changed on each pull request and each push to `main`, judged by the copy of this tool on `main` (for a push, the copy from before it). The check fails when a ratcheted item was taken away, and when a change edits `tools/metrics.py`, `.github/workflows/metrics.yml` or `.github/workflows/metrics-self-test.yml`, because that changes how changes are judged. The owner decides whether to merge over a failure.

The check stops a merge only once `main`'s ruleset requires it. Until then it reports and blocks nothing. The owner adds it there after this tool is on `main` and after a live pull request has shown that the check attaches to the pull request's head commit. The pull request that brings this tool is never judged by it, because the check runs `main`'s copy and there is none yet.

## What is measured

| Metric | Source | Rule, and what an item is |
|---|---|---|
| `kit.scenarios` | `conformance/kernel/<kind>/<name>.json` | ratcheted, by kind and name |
| `kit.scenarios.<kind>` | the same, one kind | shown |
| `kit.vectors` | `accept`, `reject`, `reject_bytes` and `collisions` in `conformance/vectors/` `canonical.json`, `core-key.json`, `core-key-more.json` and `paths.json`: the vectors the kernels are judged with | ratcheted, by name, or by the path or bytes where a vector has no name |
| `kit.tool_tree_vectors` | `conformance/vectors/tool-tree.json`, judged against the reference only | ratcheted, by name |
| `kit.vectors.<file>` | one vector file | shown |
| `kit.ledger_listed_cases` | the cases the ledger files list: `append` and `damage` in `conformance/ledger/cases.json`; `damage`, `bad_requests` and `unlisted_kind` in `more-damage.json` | ratcheted, by name; the appends by their whole content, and the unlisted kind counted |
| `kit.host_check_cases` | `cases` in `conformance/provider/check-cases.json` | ratcheted, by each case's whole content: many cases share a mode, and a reason says nothing of what a case checks, so a case changed at all is one taken away and one added, and the owner merges over that |
| `kit.session_cases` | `cases` in `conformance/provider/cases.json` | ratcheted, by mode |
| `planted_defects.kernel`, `planted_defects.kernel2` | `defects` in `kernel/defects.json` and `kernel2/defects.json` | ratcheted, by name |
| `claims.total` | rows `\| C<n> \|` in `spec/CLAIMS.md` | ratcheted, by claim id |
| `claims.checked` | claims whose status is `**checked**, run <n>`, with a heading `### Run <n>` under `## Recorded runs`, outside any fenced block; a heading of level 1 or 2 ends that section, and a fence closes only on the same character, at least as long, with nothing after it. Markdown that could hide a line or end a section unseen (an HTML block or comment, a link reference definition, an indented or underlined heading) makes the file unreadable | ratcheted, by claim id |
| `claims.unchecked` | every other claim | shown |
| `claims.sampled_by_kit`, `claims.modelled_unchecked`, `claims.not_modelled` | the other statuses, and the section "Not yet modelled" | shown |
| `decisions.total` | `decisions/[0-9]*.md` | ratcheted, by file name |
| `decisions.<status>` | the `status:` line of each record | shown |
| `gaps.not_in_kit` | the `- ` items under "Not yet in the kit" in `conformance/README.md`; any other line there is unreadable | shown |
| `gaps.gap_checks` | every "Check" table in `docs/gap-checks.md`; each check must be an entry of `GAP_CHECKS` in `tools/check_repo.py` or, where that file exists, of `CHECKS` in `tools/check_docs.py`, read from their source | ratcheted, by check name |
| `gaps.tool_checks` | the "Tool" table in `docs/gap-checks.md` | ratcheted, by its first cell |

The planted-defect lists are read for their names only. A kernel is judged by planting the defects (`tools/kit_adequacy.py`, `kernel2/plant.js`), not by this list.

`kit.vectors` counts the same 119 vectors as the README. `kit.ledger_listed_cases` is the 46 cases the two files list. It is not the README's 89 ledger checks, which are what `tools/run_ledger_cases.py` makes of those cases when it runs, including a cut at every byte.

Open GitHub issues are not measured, because they are not a file in the repository.

## Ratcheted and shown

A ratcheted metric is a set of items, each with its identity where it has one. A change fails when it takes any item away, even if it adds another, so renaming or replacing an item counts as taking one away. Where items have no identity, the count must not fall. These metrics hold what judges the project, or what the project says about itself. Taking an item away weakens a check or hides a statement, which [AGENTS.md](../AGENTS.md) rule 7 forbids unless the owner agrees.

A shown metric can move either way as the project grows:

- the unchecked claims fall when a claim is checked and rise when one is added;
- the items not yet in the kit fall when one is added to the kit and rise when a gap is found;
- the decisions by status change when the owner accepts or supersedes a record;
- the breakdowns by file change when an item moves between files, and their totals are ratcheted. Scenarios are the exception: they are ratcheted by kind and name, so moving one to another kind takes it away from the first.

In CI one copy of the tool measures both sides of a change, so a change to its list of ratchets is not seen as a metric moving. It is seen as a change to `tools/metrics.py`, which fails the check on its own. The self-test also requires the list to match the expected one. Only `--compare FILE`, against numbers saved earlier, sees a ratcheted metric that disappeared or stopped being ratcheted, and counts that as taking its items away.

Adding something the tool does not know, such as a new vector file or a new claim status, makes the tool unable to measure until it learns it, so such a change fails until `tools/metrics.py` is updated or the owner merges over it.

## When an item is taken away on purpose

Some removals are right. A scenario may judge a rule the contract no longer has. A claim must lose its checked mark when its model changes and the run that checked it no longer matches, and `tools/check_repo.py` requires that. The change still fails. Its author explains it with a line in a commit message of the change:

```
Metrics-down: kit.scenarios: the scenario judged a rule the contract dropped
```

The line starts with `Metrics-down:`, names one metric exactly and gives a reason of at least six words. The report shows it next to the failure, for the owner, and the owner decides whether to merge over the failure. The line does not make the change pass, and nobody can grant that to their own change. The report also lists lines that are not well-formed explanations (a wrong key, an unknown metric, a reason that is too short) and explanations for a metric that lost nothing.

Each change is compared with its own base, so a removal that the owner merged over does not carry forward to the next change.

## What the check cannot see

- **Its own job name, taken by another workflow.** A required check is matched by its name. The gate runs the documents gate's guard, `tools/check_docs.py jobs`, taken from the same trusted revision, which reads every workflow of the change with a YAML reader (anchors, escapes and folding resolved as GitHub reads them) and fails when another could show a job under the gate's id or name, in any letter case, or gives its token permission to post checks or statuses ([gap checks](gap-checks.md)). A check run created through the API by something other than a workflow of the change still gets past it; the ruleset must pin the required check to the GitHub Actions app.
- **Unsafe edits of its own workflow, in more detail.** The workflow guard (`workflow-check`) allows Python to run the tool and to make the YAML reader's environment, and `git show` of the tool, the documents gate's checker, the reader's pin list and its wheels from the trusted revision. It does not check the reader environment's own Python invocations, pip's flags, `git cat-file` used in place of `git show`, or whether the job-name guard's result is used. Any change to the workflow fails the gate anyway.
- **Unsafe edits of its own workflow.** The self-test reads `metrics.yml` for known ways of running or checking out the pull request's code and plants each one. That reading is advisory, because a determined edit could get past it. Any change to the workflow fails the check anyway.
- **What a file means.** The tool counts what files state. Only the host check cases and the ledger appends are tracked by their whole content. Anything tracked by a name (a scenario, which must still be JSON; a vector; a session case; a ledger damage case or bad request; a defect; a decision) can be cut down to its name and is not seen as taken away. The same holds for claims, run headings, gap checks and tool checks: a claim's text can be replaced and the claim still counts as checked; a claim marked checked by any `### Run N` heading under "Recorded runs" counts, a superseded run included; a row wrapped in Markdown that hides it from a reader (an image's alt text, a code span over several lines) still counts; a check emptied to `pass`, or `unlisted_kind` emptied to `{}`, still counts. Gap checks are read from `GAP_CHECKS`, which must be bound once, never changed, and never sliced or indexed directly. That is all: how `main` in `tools/check_repo.py` uses the list is not judged, so `list(GAP_CHECKS)[:0]`, `GAP_CHECKS * 0`, a filtering comprehension, dropping it from the loop, shadowing it with a parameter, or a loop that does not call each check all keep the count while fewer checks run. The count is of checks listed, not of checks run; what each check does is not judged either.
- **Cheap additions.** A count can be raised cheaply: a scenario that is any JSON file, a host check case copied with a key added, a heading inside a fence in "Not yet modelled" (the status loop ignores fences there). Once added, the ratchet keeps them; a reviewer has to see them come in.
- **The merge result.** A pull request is judged at its head, not merged with `main`. Two green pull requests can each add the same claim id, vector name or check case; merged, `main` has a duplicate and cannot be measured, and every pull request after fails until it is fixed. Requiring branches to be up to date before merging closes this; nothing here does.
- **False reds.** Renaming a scenario or a defect, or editing a host check case in place, takes the old one away and fails (2 of the 6 changes to `main` before this were such). A base that predates a file the tool now needs cannot be measured, so a pull request branched off before such a change fails until `main` is merged into it. A line starting with an autolink, `- item` directly followed by `---`, and JSON with a byte-order mark are refused. A changed host check case is named only by a hash of its content.
- **The self-test's own anchors.** The self-test plants faults at exact strings of today's files (for example `status: proposed` in decision 0001). When one of those changes for a good reason, the self-test cannot plant and exits 2 on every pull request until `tools/metrics.py` is updated, which the owner merges over the failure. A mutant counts as caught when any plant fails, not only the one aimed at it, and a run that exits 2 where 1 was expected counts too.


## The self-test

`python tools/metrics.py self-test` works on copies of the source files in a temporary folder, on a scratch git repository and on faulty copies of the tool itself. For each, it requires the stated exit code and, where something is taken away, that the row of that metric is the one that fails. It checks:

- that the ratcheted metrics are exactly the expected list, which is kept apart from the code that measures;
- controls that must pass: nothing changed, an item added, a shown number lowered;
- every ratcheted list taken from in turn: a scenario from each kind, an item from every vector list, ledger list, case list and defect list, a claim, a checked mark, a decision record, a gap check and a tool check;
- an item renamed in every list that has identities, however short the list, and a scenario, claim and decision renamed: each takes one away although the count is unchanged;
- a named vector replaced by one with no identity, and a scenario copied byte for byte, which takes nothing;
- a change to each of `tools/metrics.py` and the two workflows, and the gate workflow deleted, in a scratch git repository;
- explanations that are well formed, too short, empty, for another metric, for no metric or with a misspelt key, each shown and none passing the change, in text and in Markdown;
- sources that cannot be read, each of which must exit 2:
  - a renamed heading, the heading twice, a stray line, a heading or an HTML comment under "Not yet in the kit";
  - a claim row in an HTML comment or a fenced block, a gap-checks table in a fenced block, a comment in `docs/gap-checks.md`;
  - unknown statuses, and a run that is not recorded;
  - duplicate identities, unknown vector files, a vector list a file may not hold or one missing, an item of the wrong type, and names that cannot be metrics;
  - a listed gap check that no check list has, `GAP_CHECKS` bound twice or changed afterwards, and a `tools/check_repo.py` that does not parse;
  - files that are not JSON or not UTF-8, a link in place of a file in git and on disk (where the system can make links; otherwise the case is listed as SKIP), earlier files that are malformed, and an unexpected exception;
- for every ratcheted metric and each of its groups, an earlier state with one item more, which must fail, and for every shown metric an earlier number one higher, which must pass;
- that a name holding a line break, as an identity, a vector file or a kind of scenario, cannot add a line of its own to the report, such as a forged result;
- that the jobs guard finds the gate's job name and job id in another `.yml` or `.yaml` workflow, and does not find the gate's own workflow;
- the workflow guard: the gate workflow passes it, and each unsafe edit planted in it is noticed (among them write permissions, a secret, a self-hosted runner, `git -c ... checkout`, `read-tree -u`, a pipe into `bash` or `tar`, `eval`, and a loosened bootstrap test);
- that each fault planted in the tool makes its own self-test fail. `MUTANTS` in `tools/metrics.py` lists the faults, each named for what it breaks.

Each judgement is printed as it is made, with the seconds since the self-test started, and the faulty copies of the tool are reported as each one finishes. A run stopped by its time limit therefore shows how far it got and which part was slow. The full list, the count and the exit code follow at the end as before. `metrics-self-test.yml` allows the job an hour: on Windows the self-test has taken 21 to 30 minutes.
