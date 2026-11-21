# This repository's site binding

Where dodona's own model checks run, for this repository only ([decision 0023](../../decisions/0023-stage-0-checks-run-in-ci-with-disposable-helpers.md)). It is not part of dodona's design; another site supplies its own files.

| File | Holds |
|---|---|
| [executor.json](executor.json) | The command that sends one job of model-checker cases to the shared queue, its time limit, and where the checker's files are on the executor |
| [pins.json](pins.json) | The digest the executor must measure for each of those files before a result from it is accepted, and where each digest came from |
| [batch_driver.py](batch_driver.py) | Runs the cases of one job one after another inside the executor, writing each case's output and exit status. It refuses to run outside a job of the queue |
| [kernel_executor.py](kernel_executor.py) | Sends batches from the kernel's `run` command to the site's executor and returns reports from their recorded outcomes |
| [test_kernel_executor.py](test_kernel_executor.py) | Exercises the batch executor against a fake queue. The fixture hashes the exact input bytes it writes on each platform |
| [js_shard_proof.py](js_shard_proof.py) | Checks and binds one completed JavaScript fallback shard receipt to its publishing job |
| [test_js_shard_proof.py](test_js_shard_proof.py) | Exercises the JavaScript fallback receipts and publication in memory |

## Optional issue 41 JavaScript fallback

A manual Repository checks dispatch on `dodona-eight-41-js-fallback-qualified` in `sloik/dodona` runs five Ubuntu shards with at most two running at once. Each checks out `a51578c688adb6fee3970057d68c97286911873f`, builds the first kernel as the ordinary JavaScript conformance job does, runs the unchanged baseline, and then judges its own stride of the existing manifest. The raw 319-entry manifest has SHA-256 `f06ffd803d8000ed3821f0b8533f9966ed92fa7af255a5020557637277d71e00`. The selectors `1/5` through `5/5` cover 64, 64, 64, 64, and 63 positions in order.

For each selector, independently pin the workflow revision, run, attempt and numeric job ID from the authenticated attempt jobs API. Require a completed job with successful fixed-source checkout, first-kernel build, judgment, upload and binding steps. Read the `ISSUE41_JS_SHARD_ARTIFACT` line from that job's **Bind the uploaded artifact to this job** step. This line binds the source, manifest, selector and exact footer SHA-256 to the uploaded artifact's ID and archive digest. Obtain the line independently of the archive.

Download each archive by artifact ID, verify the raw archive SHA-256 and the exact `binding.json` fields against the pinned job and publication line, and verify the raw `receipt.json` SHA-256 before counting any coverage. The footer requires a completed baseline, every named catch in the shard and clean temporary-copy removal. Aggregate coverage requires five admitted receipts with no missing, duplicate or unfinished positions. Completion of a single shard establishes its own scope.
