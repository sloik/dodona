---
id: "0029"
title: A check with a current result is not run again, and the ledger is kept from one run to the next
status: proposed
date: 2026-11-18
governs:
  - tools/host.py
  - tools/keep.py
  - .github/workflows/models.yml
supersedes: []
---

# 0029. A check with a current result is not run again, and the ledger is kept from one run to the next

## Context

The design files every result under a hash of everything it depended on ([0006](0006-evidence-key-and-trusted-base.md)), and a kernel already counts a result only while that hash matches the inputs as they are now. But every change to `main` still ran all 94 model checks on the shared queue, because each run started with an empty ledger. The design promised reuse and the practice did not use it.

## Decision

**The ledger is kept.** Each successful model run on `main` keeps its ledger, and the lists of states the two dump models wrote, as a build artifact for 90 days. The next run starts from the ledger of the last successful run.

**A kernel decides what runs.** Before anything is sent, `tools/host.py plan` builds the same status scenario the status report uses and asks the kernel which checks are `passed` or `failed` from records that count: written by this writer, on this platform, under the key of the inputs, tools and provider as they are now. Those are not run again. Everything else is: never run, an error, a conflict, or a record under an old key.

**The hash does the invalidating.** An edit to a model's files, a different pinned tool, a new provider version, or a kernel that computes keys differently all change the key, and the old result stops counting by itself. Nothing is invalidated by hand.

**What a result depends on, in full.** A review found three things the key left out, each of which let a result be reused after it should have stopped counting: the provider's code (only its stated version was in the key), the names of the model files (only their contents were), and whether a list of states came from a run that finished. All three are now in. A case the provider cannot make into a check turns the run red instead of disappearing, and a job that sent anything is judged for completion even when no check was among it.

**Lists of states are kept the same way.** A dump model's list of states is reused while its files and the pinned tools are unchanged. A list is kept only from a dump run that ended with status 0 and reported searching everything.

**The run summary says what happened.** How many checks ran, how many kept their result and from which run, and the status of every check now. The run fails unless every check has a passing result for the inputs as they are now.

## Consequences

- A change that touches no model sends no job to the shared queue.
- A run that fails keeps nothing, so the run after it starts from the last success. That can mean running more than needed. It never means trusting a failed run's ledger.
- The starting point is the last successful run that a push to this repository's `main` started. A pull request's run, or a fork's with a branch named `main`, is never used: a review showed the first version would have taken one.
- Results are trusted because the artifact comes from a run on `main` of this repository. Anyone who can write to `main` or to its workflow runs can also write the kept ledger; that is the same trust as the code itself.
- If the artifact has expired or cannot be fetched, every check runs. Nothing is reused by default.

## What would show this wrong

- A check reused after one of its model files, its tools or its provider changed.
- A check run again although nothing it depends on changed.
- A run reported green while a check has no passing result for the current inputs.
- A ledger from a failed run, or from another branch, used as the starting point.
