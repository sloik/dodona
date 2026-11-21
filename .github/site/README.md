# This repository's site binding

Where dodona's own model checks run, for this repository only ([decision 0023](../../decisions/0023-stage-0-checks-run-in-ci-with-disposable-helpers.md)). It is not part of dodona's design; another site supplies its own files.

| File | Holds |
|---|---|
| [executor.json](executor.json) | The command that sends one job of model-checker cases to the shared queue, its time limit, and where the checker's files are on the executor |
| [pins.json](pins.json) | The digest the executor must measure for each of those files before a result from it is accepted, and where each digest came from |
| [batch_driver.py](batch_driver.py) | Runs the cases of one job one after another inside the executor, writing each case's output and exit status. It refuses to run outside a job of the queue |
| [kernel_executor.py](kernel_executor.py) | Sends batches from the kernel's `run` command to the site's executor and returns reports from their recorded outcomes |
| [test_kernel_executor.py](test_kernel_executor.py) | Exercises the batch executor against a fake queue. The fixture hashes the exact input bytes it writes on each platform |

## Retained native status pair

[replay_retained_status.py](replay_retained_status.py) is a hosted proof for the composed Rust and JavaScript status sources at `4462d9b`, qualified at `a1dba84` and recorded as Run 15 at `ee24e67`. On the proof checkout, `python .github/site/replay_retained_status.py --check-checkout` binds `GITHUB_SHA` to the checkout. It checks the exact record paths between the runtime and recorded commits, then permits only the proof's site files and manual workflow to differ from the recorded commit.

The `native-status-pair` job in Repository checks runs on manual dispatch of the `dodona-eight-40-native-status-pair-proof` branch. It builds the first kernel with `cargo build --release --locked --manifest-path kernel/Cargo.toml` and uses an isolated Python environment with `jsonschema` for the existing policy reader.

Fetch each archive and its GitHub API metadata into its own runner temporary directory. Both `RETAINED` and `PRIOR` hold `run.json` from `actions/runs/{run}`, `artifact.json` from `actions/artifacts/{artifact}`, and `archive.zip` from `actions/artifacts/{artifact}/zip` in `sloik/dodona`. `RETAINED` uses run `44626497885` and artifact `14582487546`. `PRIOR` uses run `44925244772` and artifact `14716281818`. Invoke `python .github/site/replay_retained_status.py RETAINED PRIOR RECEIPT` with `RECEIPT` a fresh output directory.

The helper checks both archives and their member digests, verifies the pinned policy, and sends identical request bytes to both native `status` commands. It compares all response fields, including the full `judged` scenario and report, with each other and the earlier receipt. The archived request is compared after accounting for runner-local checkout and Python paths. The receipt keeps both native outputs, the request, the exact elapsed nanoseconds of each native command, and a completion marker after agreement. [The controls](test_replay_retained_status.py) exercise the refusal and comparison checks in memory.
