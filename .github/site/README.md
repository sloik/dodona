# This repository's site binding

Where dodona's own model checks run, for this repository only ([decision 0023](../../decisions/0023-stage-0-checks-run-in-ci-with-disposable-helpers.md)). It is not part of dodona's design; another site supplies its own files.

| File | Holds |
|---|---|
| [executor.json](executor.json) | The command that sends one job of model-checker cases to the shared queue, its time limit, and where the checker's files are on the executor |
| [pins.json](pins.json) | The digest the executor must measure for each of those files before a result from it is accepted, and where each digest came from |
| [batch_driver.py](batch_driver.py) | Runs the cases of one job one after another inside the executor, writing each case's output and exit status. It refuses to run outside a job of the queue |
| [kernel_executor.py](kernel_executor.py) | Sends batches from the kernel's `run` command to the site's executor and returns reports from their recorded outcomes |
| [test_kernel_executor.py](test_kernel_executor.py) | Exercises the batch executor against a fake queue. The fixture hashes the exact input bytes it writes on each platform |

## Final status proof

The manual `dodona-eight-40-final-status-proof` branch of [Repository checks](../workflows/checks.yml) runs two proof lanes for the final-report changes. The ordinary and planted jobs skip this manual lane. The jobs use the exact dispatched revision and the focused status job verifies that both kernels, the conformance fixtures, and the judge tools match source `4462d9bce3851027cfa7f37d2d1ceb49f0085a3e`.

- The retained-state job uses artifact `14581497930` from completed main run `44626497885`. It retains the original ZIP, model, configuration and tool pins from run 13's workflow. It compares 71,744 evidence states and 78,894 intent states with each kernel. It reads the retained data and makes no model-checker call. C37 remains unchecked on the changed input bundle until all four comparisons finish in agreement and the exact receipt is recorded.
- [final_status_proof.py](final_status_proof.py) runs the exact Rust final-report test, seven named Node controls, and the 253 curated status cases against each kernel on macOS, Linux and Windows. The status judge uses the reference command and the other kernel's `scenario` command to recompute the report. Each matrix job has 30 minutes. The Rust test, Node controls, release build, and each status judge have limits of eight minutes, one minute, ten minutes, and six minutes respectively. The receipt requires native exit 0 for every command, exact passing unit test identities and all case rows accounted for. It records specific Windows link or permission skips declared by the fixture, and requires both kernels to cover the same cases. The current status judge's nonzero exit cannot establish whether a disagreement or an infrastructure failure occurred. Such a result leaves the receipt unfinished.

Each successful status matrix job uploads a separate artifact named `final-status-proof-SYSTEM-RUN-ATTEMPT`. Its JSON records the checked-out revision, pinned source, run and attempt, platform, unit controls, status counts and skip names, case-file digest and built Rust executable digest. A recipient checks that all three selected jobs, including their artifact upload steps, finished successfully on the expected revision and that the artifacts and receipt fields agree with that run. The retained-state artifact is separate. Run the offline controls with `python3 .github/site/test_final_status_proof.py`.
