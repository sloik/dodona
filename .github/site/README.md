# This repository's site binding

Where dodona's own model checks run, for this repository only ([decision 0023](../../decisions/0023-stage-0-checks-run-in-ci-with-disposable-helpers.md)). It is not part of dodona's design; another site supplies its own files.

| File | Holds |
|---|---|
| [executor.json](executor.json) | The command that sends one job of model-checker cases to the shared queue, its time limit, and where the checker's files are on the executor |
| [pins.json](pins.json) | The digest the executor must measure for each of those files before a result from it is accepted, and where each digest came from |
| [batch_driver.py](batch_driver.py) | Runs the cases of one job one after another inside the executor, writing each case's output and exit status. It refuses to run outside a job of the queue |
| [kernel_executor.py](kernel_executor.py) | Sends batches from the kernel's `run` command to the site's executor and returns reports from their recorded outcomes |
| [test_kernel_executor.py](test_kernel_executor.py) | Exercises the batch executor against a fake queue. The fixture hashes the exact input bytes it writes on each platform |
| [rust_shard_proof.py](rust_shard_proof.py) | Captures one passing Rust fallback shard and binds the exact receipt bytes to the publishing job's upload |
| [test_rust_shard_proof.py](test_rust_shard_proof.py) | Exercises the fallback receipt and publication checks with mock jobs and processes |

## Optional issue 41 Rust fallback

The manual `checks.yml` lane on `dodona-eight-41-rust-fallback-qualified` in `sloik/dodona` runs only the five Ubuntu Rust shard jobs, at most two at a time. The source checkout is `2047e108f6adcec36b554822a1b9f4b598a1fcf1`. It includes the held-lock judge correction and mocked controls. Its 275-defect manifest has raw SHA-256 `5c3d6816102c81e7b83eedf8b784e65e0b8602869624f9143bc76546f463194a`. Each shard uses the runner's unchanged-kernel baseline and the same named-case replay as the full suite. Use this dormant lane only when a serial or default run has actually timed out or finished without a complete tally. Aggregate coverage belongs to this source and plan.

1. Independently pin the workflow revision, repository, run ID and attempt, and expected selectors `1/5` through `5/5`. Find the numeric job IDs through `GET /repos/{owner}/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs`. Require completed success for each shard job, including its fixed-source checkout, judge, upload and binding steps.
2. Read the `ISSUE41_RUST_SHARD_ARTIFACT` record from that job's **Bind the uploaded artifact to this job** step log. Check its source and manifest pins, selector, workflow revision, run ID and attempt. Use the reported artifact ID and archive SHA-256 to bind the upload to this job. Artifact names and run-level artifact listings alone cannot establish that link.
3. Download by artifact ID and verify the raw archive digest against that record. Require `receipt.json` and `binding.json`. Match the archived binding to the publication record's fields and verify the raw `receipt.json` SHA-256. Supply those verified footer files and the pinned raw manifest to the separate aggregator with `--expected-count 5`. A missing or failed publication step leaves the shard incomplete. The binding parts use the hosted job identity and the source checkout as separate inputs.
