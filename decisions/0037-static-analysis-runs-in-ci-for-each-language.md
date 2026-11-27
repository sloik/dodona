---
id: "0037"
title: Static analysis runs in CI for each language and format the repository holds
status: proposed
date: 2026-11-22
governs:
  - .github/workflows/lint.yml
  - .github/lint-tools.txt
  - .github/actionlint.yaml
  - .github/zizmor.yml
  - ruff.toml
  - eslint.config.mjs
  - .editorconfig
supersedes: []
---

# 0037. Static analysis runs in CI for each language and format the repository holds

## Context

The repository holds Python (the stage-0 tools, the reference providers, the kit's helpers and the site binding), JavaScript (the second kernel), Rust (the first kernel), GitHub workflows, JSON, TOML, Markdown and TLA+. `tools/check_repo.py` already parses every JSON and TOML file, checks line endings, compiles every tool and reads the workflows for unpinned actions and unsafe triggers ([gap checks](../docs/gap-checks.md)), and `tools/check_docs.py` resolves the links in Markdown. Nothing looked at the code itself for the mistakes a linter finds without running it: a name that is never defined, an import never used, a function declared twice, a shell error in a workflow's `run:` block, or a pinned commit that does not belong to the action it names. When first run, the linters found a function the second kernel declares twice and eight unused imports, which are removed with this record.

## Decision

A workflow of its own, [lint.yml](../.github/workflows/lint.yml), described in [static checks](../docs/static-checks.md), runs one widely used linter for each language and format, on every pull request and every push to `main`. Each tool is pinned to one version, and its rules live in a configuration file in the repository, never in the workflow:

| What | Tool | Rules |
|---|---|---|
| Python | ruff, lint only | [ruff.toml](../ruff.toml): syntax errors, pyflakes, and pycodestyle's likely-mistake rules (`E4`, `E7`, `E9`, `F`) |
| JavaScript | ESLint | [eslint.config.mjs](../eslint.config.mjs): ESLint's recommended set, written out with two changes |
| Rust | clippy | default Clippy lints from Rust 1.100.0 with warnings treated as errors |
| Workflows | actionlint, with the runner's shellcheck; zizmor | [.github/actionlint.yaml](../.github/actionlint.yaml), [.github/zizmor.yml](../.github/zizmor.yml) |
| Editors | EditorConfig | [.editorconfig](../.editorconfig): only what the repository checks already require |

The Python tools are installed from a list of exact versions and hashes ([.github/lint-tools.txt](../.github/lint-tools.txt)). Go's checksum database verifies the tagged actionlint build. ESLint is installed from its [tooling dependency lock](../.github/eslint/package-lock.json) with `npm ci`. Clippy runs on macOS, Linux and Windows, because the first kernel has code for one system only; the other tools read files and give the same answer on any system, so they run on Linux.

A last job, `lint`, needs every other job of the workflow, runs whatever their outcome, and passes only if each of them succeeded: a job that failed, was skipped or was cancelled fails it. `lint` is the one name `main`'s ruleset is to require for this workflow. A required check is matched by its name, so requiring the jobs one by one would leave a required check waiting for ever once a job or a matrix entry is renamed; the jobs behind `lint` can change without touching the ruleset.

A rule is left off only with its reason written next to it in the configuration, and listed below. The kernels name no tool: every configuration lives at the root of the repository or under `.github/`.

The Ruff F401 waiver applies to the retained `fnmatch` import in `tools/metrics.py`.

ESLint reports no-redeclare errors throughout the second kernel. The duplicate `isObject` implementation was removed with a new recorded comparison for C37.

## Left for later

Each of these breaks on the code as it is now, and is left off rather than met by rewriting it:

- `ruff format`: 55 Python files would be reformatted.
- ruff 0.17.6's own default selection, which is wider than the rules above: 191 findings, among them B023 (a function that uses a loop variable, nine times), PLW1510 (`subprocess.run` without `check`, 41 times) and many style rules. B023 is worth reading first, as it can be a real mistake.
- ruff E701, E702, E731 and E741: statements on one line, lambdas assigned to names, and `l` as a name; style, in many places.
- ruff F841 on one line of `tools/check_repo.py`: `problems_before` is set and never read in `gap_an_intent_reads_one_way_only`. It is dead code, not a defect: a review showed the check still fails as it should. It is marked `# noqa: F841` on that line and kept, because `tools/check_repo.py` is a judged file.
- `cargo fmt --check`: a formatting pass would need to preserve the exact textual anchors of planted defects in the first kernel.
- Markdown style: links and anchors are already checked by `tools/check_docs.py`.
- TLA+: no checker of the specifications runs outside the model queue.

Some exceptions are not left for later but are part of the rules, each for the exact place it excuses: ruff's F821 on four lines of `conformance/provider/misbehaving_checker.py` (`# noqa: F821`), which use a name the file sets through `globals()`; zizmor's `dangerous-triggers` at the `pull_request_target` trigger of `docs.yml` and of `metrics.yml`, named by line and column, which is the point of the trusted gates and is guarded by `gap_workflows_are_safe` and the metrics workflow guard; and zizmor's two informational `template-injection` findings on one line of `checks.yml`, by line and column, which expand `strategy.job-index` and `strategy.job-total`, numbers GitHub sets from the matrix. A zizmor exception named by position stops matching once lines above it move, and the finding then fails the job until the position is updated; that is the price of an exception that cannot cover a second finding, such as a `workflow_run` trigger added to the same file. Each exception is written, with its reason, beside it.

## Consequences

- A pull request that adds an undefined name, an unused import, a redeclared function or an unsafe workflow step fails a check before anyone reads it.
- Moving a linter to a new version is a change of its own, which may bring new findings.
- Nothing here is required by `main`'s ruleset until the owner adds `lint` there; only then does a lint failure block a merge.
- A new lint job must be added to the `needs` of `lint`, or its failure blocks nothing.

## Alternatives rejected

- Rules in `tools/check_repo.py`: a linter's rules are what other projects already know, and writing them again would be a second implementation to keep right.
- A `package.json` and a lock file for ESLint: the second kernel has no dependencies, and a manifest would suggest that it does.
- Every rule on, with the code rewritten to meet it: a large change of no meaning to the kernels, against the planted defects that replace exact text.

## What would show this wrong

A mistake reaches `main` that one of these tools, with the rules here, reports when run on the change; or a lint job fails on a change that does not touch what it checks.
