# Static checks

Linters that read the code without running it, one for each language and format the repository holds. They run on every pull request and every push to `main` in [lint.yml](../.github/workflows/lint.yml). [Decision 0037](../decisions/0037-static-analysis-runs-in-ci-for-each-language.md) says why, and which rules are left for later. Checks that are this project's own, such as files that parse, links that resolve and workflows that are safe, are in [gap-checks.md](gap-checks.md).

| Job | Tool and version | Rules | What it reads |
|---|---|---|---|
| `lint (Python and workflows)` | ruff 0.17.6 | [ruff.toml](../ruff.toml) | every Python file |
| `lint (Python and workflows)` | actionlint 1.7.12, with the runner image's shellcheck | [.github/actionlint.yaml](../.github/actionlint.yaml) | `.github/workflows/` |
| `lint (Python and workflows)` | zizmor 1.32.0 | [.github/zizmor.yml](../.github/zizmor.yml) | `.github/workflows/` |
| `lint (JavaScript)` | ESLint 10.15.0 | [eslint.config.mjs](../eslint.config.mjs) | `kernel2/` |
| `lint (Rust, macos)`, `(linux)`, `(windows)` | clippy of the runner's Rust | clippy's defaults: errors fail, warnings are shown | `kernel/` |

ruff and zizmor are installed from [.github/lint-tools.txt](../.github/lint-tools.txt), which pins each version with the hash of every file published for it. actionlint is built at its tag with Go, whose checksum database verifies what it fetches. ESLint runs at its exact version through `npx`; what ESLint itself depends on is not locked. zizmor is given the job's read-only token, so that it can ask GitHub whether each pinned commit belongs to the action it names.

[.editorconfig](../.editorconfig) tells editors what the repository checks already require: UTF-8 and line feeds. It leaves the kit's data and the saved run outputs alone, because their bytes are hashed as they are.

## Running them before a push

From the root of the repository, with the same versions:

```
python -m pip install --no-deps --require-hashes -r .github/lint-tools.txt
ruff check .
zizmor --min-severity low .github/workflows
actionlint
npx --yes eslint@10.15.0 kernel2
cargo clippy --locked --all-targets --manifest-path kernel/Cargo.toml
```

A rule is turned off only in the configuration file, with its reason beside it, and is listed under "Left for later" in decision 0037 until it is turned on.
