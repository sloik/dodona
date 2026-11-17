---
id: "0023"
title: Stage-0 checks run in CI, with disposable helpers
status: proposed
direction: owner
date: 2026-11-17
governs:
  - tools/
  - .github/
supersedes: []
---

# 0023. Stage-0 checks run in CI, with disposable helpers

## Context

dodona has formal models and claims about them, and no kernel to run or judge them. Running them by hand does not scale and leaves no public trace. The project's rule is that nothing is called checked unless a run is on record.

## Decision

Until a kernel exists, two small scripts in `tools/` do what dodona will later do for itself. One runs the checks that need no model checker, on macOS, Linux and Windows. The other hands every case in `spec/*/expected.json` to an executor and judges the result: a case matches only when the exit code and the checker's own output both agree with what was expected, and a run that did not finish is a failure.

The scripts follow dodona's own rules where they can. The judge never starts a model checker; it is given the executor by a site file ([0007](0007-execution-backend-is-separate-from-the-verifier.md)). No shell is used. The judge's refusal to accept an unfinished run is itself tested.

The site file and the workflows under `.github/` are this repository's own site binding: they say where the dodona project's checks run. They are the one place site-specific detail is allowed, they are labelled as such, and nothing in dodona's design depends on them.

Model checks run only for the maintained main branch on the project's own runner, never for pull requests, so that code from a fork does not execute there.

The scripts are disposable. They are written in a scripting language because that is what runs unmodified on all three platforms today; this is not a choice of implementation language for dodona ([0011](0011-self-hosting-through-a-verified-seed.md)). They are deleted when a kernel can do the same job.

## Consequences

- Every push shows publicly whether the repository's own claims still hold.
- A contributor's pull request gets the platform-independent checks; the model checks run after merge.
- There is a small amount of code outside dodona's own discipline, kept deliberately small.

## Alternatives rejected

- Wait for the kernel: leaves the design unverified in public for as long as that takes.
- Run model checks on shared hosted runners: possible for others, but this project's checks run on its own executor.

## What would show this wrong

A workflow run is green while a case in `expected.json` did not produce its expected outcome, or the helpers grow into something a kernel would have to be compatible with.
