# This repository's site binding

Where dodona's own model checks run, for this repository only ([decision 0023](../../decisions/0023-stage-0-checks-run-in-ci-with-disposable-helpers.md)). It is not part of dodona's design; another site supplies its own files.

| File | Holds |
|---|---|
| [executor.json](executor.json) | The command that sends one job of model-checker cases to the shared queue, its time limit, and where the checker's files are on the executor |
| [pins.json](pins.json) | The digest the executor must measure for each of those files before a result from it is accepted, and where each digest came from |
| [batch_driver.py](batch_driver.py) | Runs the cases of one job one after another inside the executor, writing each case's output and exit status. It refuses to run outside a job of the queue |
| [kernel_executor.py](kernel_executor.py) | Sends batches from the kernel's `run` command to the site's executor and returns reports from their recorded outcomes |
| [test_kernel_executor.py](test_kernel_executor.py) | Exercises the batch executor against a fake queue. The fixture hashes the exact input bytes it writes on each platform |

## Held-ledger qualification

The manual `dodona-eight-41-held-ledger-proof` branch of [Repository checks](../workflows/checks.yml) qualifies the ordinary ledger judge at `15fe061c47d5cef91fa4c7c0b88e872af485e5f0` on macOS, Linux and Windows. The ordinary and planted jobs skip this manual lane. [The proof helper](held_ledger_proof.py) checks the dispatched revision and pinned source, runs the ten existing ledger judge mocks, builds the unchanged Rust kernel, and gives both unmodified kernels the same standard 110 owned-fixture ledger checks. The named held-lock and two-writer cases must match. The lane runs no native planted defects.

Each 20-minute matrix job uploads `held-ledger-proof-SYSTEM-RUN-ATTEMPT` only after both judges exit 0 with 110 distinct matching rows, no diagnostics on stderr, and complete and consistent typed footers. Its JSON binds the checked-out revision, pinned source, run, attempt, platform, fixture digest and the mock and native exit counts. The recipient checks the exact three successful jobs and their uploaded receipts. This is evidence about the unchanged kernels and the mocked judge controls. A C20 catch tally remains pending.
