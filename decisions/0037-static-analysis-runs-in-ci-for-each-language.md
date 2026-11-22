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

A workflow of its own, [lint.yml](../.github/workflows/lint.yml), runs one widely used linter for each language and format, on every pull request and every push to `main`. Each tool is pinned to one version, and its rules live in a configuration file in the repository, never in the workflow:

| What | Tool | Rules |
|---|---|---|
| Python | ruff, lint only | [ruff.toml](../ruff.toml): ruff's default set (syntax errors, pyflakes, pycodestyle's likely-mistake rules) |
| JavaScript | ESLint | [eslint.config.mjs](../eslint.config.mjs): ESLint's recommended set, written out so no package is installed |
| Rust | clippy | clippy's defaults; a lint that is an error by default fails the job, a warning does not |
| Workflows | actionlint, with the runner's shellcheck; zizmor | [.github/actionlint.yaml](../.github/actionlint.yaml), [.github/zizmor.yml](../.github/zizmor.yml) |
| Editors | EditorConfig | [.editorconfig](../.editorconfig): only what the repository checks already require |

The Python tools are installed from a list of exact versions and hashes ([.github/lint-tools.txt](../.github/lint-tools.txt)); actionlint is built at a tagged version through Go's checksum database; ESLint is run at an exact version with `npx`. Clippy runs on macOS, Linux and Windows, because the first kernel has code for one system only; the other tools read files and give the same answer on any system, so they run on Linux.

A rule is left off only with its reason written next to it in the configuration, and listed below. The kernels name no tool: every configuration lives at the root of the repository or under `.github/`.

## Left for later

Each of these breaks on the code as it is now, and is left off rather than met by rewriting it:

- `ruff format`: 55 Python files would be reformatted.
- ruff E701, E702, E731 and E741: statements on one line, lambdas assigned to names, and `l` as a name; style, in many places.
- ruff F401 in `tools/metrics.py`: one unused import, in a file being changed elsewhere.
- ruff F841 in `tools/check_repo.py`: `problems_before` is set and never read in `gap_an_intent_reads_one_way_only`. It may be a comparison that was never written, so it is left for the owner.
- ESLint's no-redeclare in `kernel2/status.js`: `isObject` is declared twice there, with the same body. The file's exact bytes are an input of the recorded run behind claim C37 (`spec/runs/index.json`), so removing the copy waits for a change that records a new run.
- `cargo fmt --check` and clippy's warnings as errors: eight formatting hunks and six warnings in the first kernel. Its source is the anchor of planted defects that replace exact text, and clippy's warnings change with the runner's Rust, so both wait for a pinned toolchain.
- Markdown style: links and anchors are already checked by `tools/check_docs.py`.
- TLA+: no checker of the specifications runs outside the model queue.

Two exceptions are not left for later but are part of the rules: ruff's F821 is off for `conformance/provider/misbehaving_checker.py`, which sets the name through `globals()`; zizmor's `dangerous-triggers` is off for `docs.yml` and `metrics.yml`, whose `pull_request_target` is the point of the trusted gates and is guarded by `gap_workflows_are_safe` and the metrics workflow guard.

## Consequences

- A pull request that adds an undefined name, an unused import, a redeclared function or an unsafe workflow step fails a check before anyone reads it.
- Moving a linter to a new version is a change of its own, which may bring new findings.
- The jobs are not required by `main`'s ruleset until the owner adds them there.

## Alternatives rejected

- Rules in `tools/check_repo.py`: a linter's rules are what other projects already know, and writing them again would be a second implementation to keep right.
- A `package.json` and a lock file for ESLint: the second kernel has no dependencies, and a manifest would suggest that it does.
- Every rule on, with the code rewritten to meet it: a large change of no meaning to the kernels, against the planted defects that replace exact text.

## What would show this wrong

A mistake reaches `main` that one of these tools, with the rules here, reports when run on the change; or a lint job fails on a change that does not touch what it checks.
