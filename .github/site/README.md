# This repository's site binding

Where dodona's own model checks run, for this repository only ([decision 0023](../../decisions/0023-stage-0-checks-run-in-ci-with-disposable-helpers.md)). It is not part of dodona's design; another site supplies its own files.

| File | Holds |
|---|---|
| [executor.json](executor.json) | The command that sends one job of model-checker cases to the shared queue, its time limit, and where the checker's files are on the executor |
| [pins.json](pins.json) | The digest the executor must measure for each of those files before a result from it is accepted, and where each digest came from |
| [batch_driver.py](batch_driver.py) | Runs the cases of one job one after another inside the executor, writing each case's output and exit status. It refuses to run outside a job of the queue |
| [kernel_executor.py](kernel_executor.py) | Sends batches from the kernel's `run` command to the site's executor and returns reports from their recorded outcomes |
| [model_request.py](model_request.py) | Prepares the policy at the workflow's push commit and builds native `run` and `status` requests from that policy |
| [model_results.py](model_results.py) | Checks the independently read ledger, the complete expected model inventory and the raw outcome of every newly run case |
| [test_kernel_executor.py](test_kernel_executor.py) | Exercises the batch executor against a fake queue. The fixture hashes the exact input bytes it writes on each platform |

Executor reports use the measured digest for a fixed pin and the site's floor key when the measured version meets that floor. The fake-queue tests check that a mismatched request cannot change either reported key.

The driver applies the provider's individual wall limit when supplied. It records a timeout before continuing to the next case. The executor reports it only after the queue has confirmed completion of the batch. Partial kept artifacts are discarded and the case output remains available for diagnosis.

The native workflow input reads `policy.toml` from the protected push commit. It can validate the policy and record the commit and digest with the reduced policy. Each request compares that artifact with its own checkout before it can start a provider. Both requests use the same writer, policy, tool pins and ledger. The site's two-hour minimum batch wait allows time for queue admission ahead of the one-hour queue job limit and preserves each case's own limit.

The model result gate requires a current pass for every case listed in the protected models and agreement between the two native reports. It pairs each newly run case with its transcript and recomputes the key of its captured output. The ordinary model judge checks each exit and expected outcome. A run that reuses every result still needs the full current inventory and agreement.

The dump plan contains only state-dump work. It reuses a dump when its existing key matches and the state file is still present. The model obligations are planned by native `run`.

The protected workflow builds a static ARM64 seed and checks the archive digest before invoking it on the project runner. It keeps the native ledger, captured outputs and both provider transcripts with the run. The hosted comparison reads that ledger with the second kernel and validates those transcripts before publishing the next retained ledger.
