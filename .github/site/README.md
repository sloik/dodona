# This repository's site binding

Where dodona's own model checks run, for this repository only ([decision 0023](../../decisions/0023-stage-0-checks-run-in-ci-with-disposable-helpers.md)). It is not part of dodona's design; another site supplies its own files.

| File | Holds |
|---|---|
| [executor.json](executor.json) | The command that sends one job of model-checker cases to the shared queue, its time limit, and where the checker's files are on the executor |
| [pins.json](pins.json) | The digest the executor must measure for each of those files before a result from it is accepted, and where each digest came from |
| [batch_driver.py](batch_driver.py) | Runs the cases of one job one after another inside the executor, writing each case's output and exit status. It refuses to run outside a job of the queue |
| [kernel_executor.py](kernel_executor.py) | Sends batches from the kernel's `run` command to the site's executor and returns reports from their recorded outcomes |
| [test_kernel_executor.py](test_kernel_executor.py) | Exercises the batch executor against a fake queue. The fixture hashes the exact input bytes it writes on each platform |

## Held-ledger qualification on Windows

The manual `dodona-eight-41-held-ledger-windows-retry` branch of [Repository checks](../workflows/checks.yml) reruns the ten ledger judge mocks and the two ordinary 110-case ledger checks on Windows. [The proof helper](held_ledger_proof.py) checks the proof revision and exact source `7328f10c5f466d344625bad397e0e697a7921af9`. It publishes a completed receipt only when each native ledger judge exits 0 with all 110 distinct checks matching and no unfinished case.

The previous Linux and macOS jobs both completed all 110 cases for each kernel. The kernel trees, ledger judge, and byte-exact ledger fixtures in this retry match those of that completed run. Its Windows job failed before starting the ordinary ledger checks because the mock unnecessarily decoded the deeply nested request. The mock correction keeps those request bytes and the full ledger judge inventory. [Previous qualification run](https://github.com/sloik/dodona/actions/runs/44933112898).
