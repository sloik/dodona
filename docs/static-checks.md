# Static checks

Linters that read the code without running it, one for each language and format the repository holds. They run on every pull request and every push to `main` in [lint.yml](../.github/workflows/lint.yml). [Decision 0037](../decisions/0037-static-analysis-runs-in-ci-for-each-language.md) says why, and which rules are left for later. Checks that are this project's own, such as files that parse, links that resolve and workflows that are safe, are in [gap-checks.md](gap-checks.md).

| Job | Tool and version | Rules | What it reads |
|---|---|---|---|
| `lint (Python and workflows)` | ruff 0.17.6 | [ruff.toml](../ruff.toml) | every Python file |
| `lint (Python and workflows)` | actionlint 1.7.12, built with Go 1.27.4 and run with the runner image's shellcheck | [.github/actionlint.yaml](../.github/actionlint.yaml) | `.github/workflows/` |
| `lint (Python and workflows)` | zizmor 1.32.0 | [.github/zizmor.yml](../.github/zizmor.yml) | `.github/workflows/` |
| `lint (JavaScript)` | ESLint 10.15.0 | [eslint.config.mjs](../eslint.config.mjs) | `kernel2/` |
| `lint (Rust, macos)`, `(linux)`, `(windows)` | clippy of the runner's Rust | clippy's defaults: errors fail, warnings are shown | `kernel/` |
| `lint` | none | every job above succeeded | the results of the jobs above |

The last job, `lint`, needs every job above and passes only if each one succeeded; a job that failed, was skipped or was cancelled fails it. **`lint` is the single name `main`'s ruleset requires for this workflow**, so a job or a matrix entry can be renamed, added or removed without leaving a required check waiting for ever. A new lint job must be added to the `needs` of `lint`, with its own result variable and success test in the aggregate Bash step. The lint workflow rejects `continue-on-error` on jobs and steps so a failure reaches the aggregate and the ruleset.

The repository checker reads jobs in both workflow extensions with the existing hash-pinned YAML wheel. It verifies the pin and unpacks the wheel outside the checkout before importing the reader. It reserves the `lint` check name for the aggregate job and refuses ambiguous computed names that could resolve to `lint`. The parsed job map also accounts for quoted, anchored, commented and flow-style dependency jobs. [GitHub guidance on required check names](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

ruff and zizmor are installed from [.github/lint-tools.txt](../.github/lint-tools.txt), which pins each version with the hash of every file published for it. actionlint is built at its tag with Go, whose checksum database verifies what it fetches. ESLint runs at its exact version through `npx`; what ESLint itself depends on is not locked. zizmor is given the job's read-only token, so that it can ask GitHub whether each pinned commit belongs to the action it names.

[.editorconfig](../.editorconfig) tells editors what the repository checks already require: UTF-8 and line feeds. It leaves the kit's data and the saved run outputs alone, because their bytes are hashed as they are.

## Running them before a push

From the root of the repository, with the same versions:

```
python -m pip install --no-deps --require-hashes -r .github/lint-tools.txt
ruff check .
zizmor .github/workflows
actionlint
npx --yes eslint@10.15.0 kernel2
cargo clippy --locked --all-targets --manifest-path kernel/Cargo.toml
```

A rule is turned off only for the exact place it excuses, with its reason beside it: a `# noqa` comment on the line for ruff, a line and column in `.github/zizmor.yml` for zizmor. Two are wider, each because the file it would need cannot be changed now: ruff's F401 for all of `tools/metrics.py`, until another pull request (#55) that changes it has merged, and ESLint's no-redeclare for all of `kernel2/status.js`, whose bytes a recorded run pins and whose line ESLint's configuration cannot name. A zizmor exception named by position stops matching once lines above it move, and the job then fails until the position is updated. Every rule left off is listed under "Left for later" in decision 0037 until it is turned on.

The ESLint configuration reads `.js`, `.mjs` and `.cjs` files under `kernel2/`.

`tools/check_repo.py` checks this workflow too: `gap_lint_aggregate_needs_every_job` requires `lint` to need every other job, run with `if: always()` and test every needed job’s result in its Bash step, and `gap_workflows_are_safe` requires each checkout step to set a literal false `persist-credentials` input in its `with` mapping. It reads both workflow extensions and nested `action.yml` or `action.yaml` composite manifests in the local actions subdirectory of [`.github`](../.github). External action references require commit pins, and local references must identify a parsed file in that inventory. The check refuses the `workflow_run` trigger. [Gap checks](gap-checks.md) · [GitHub action metadata](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax).

The zizmor positions in the repository workflow follow the shard invocations when platform check steps move them.
