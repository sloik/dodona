---
id: "0033"
title: A kernel hosts providers itself, and one status command reports on a project
status: proposed
date: 2026-11-19
governs:
  - kernel/
  - kernel2/
  - conformance/README.md
  - tools/run_check_cases.py
supersedes: []
amends:
  - "0023"
  - "0026"
---

# 0033. A kernel hosts providers itself, and one status command reports on a project

[Decision 0034](0034-a-kernel-runs-a-project-and-reports-its-status.md) amends this decision with the project-level commands.

## Context

Decision 0026 made the first host a stage-0 helper, `tools/host.py`, and the first status report another, `tools/status.py`. They join a provider, an executor and a kernel, and they keep the rules a schema cannot express: what a run may start, which files it may name, that a verdict rests on a run and claims no more strength than declared. Those rules are where most of the protection against a provider that misbehaves lies, and they live in a helper written by the same author as the tests that judge them. A kernel is the part of dodona meant to be trusted; the rules belong in it, held to the same kit by two independent kernels.

## Decision

- **A kernel hosts providers.** Each kernel gains the commands that `tools/provider_host.py` and `tools/host.py check` stand in for now: a provider session (hello, manifest, requests, shutdown, every process ended) and one check taken from a provider to a verdict, with each run given to an executor command. The interface and every rule are in conformance/README.md ("How a host is judged" and "Host checks"), judged by `tools/run_provider_cases.py` and `tools/run_check_cases.py`. The kernel names no tool (AGENTS.md rule 5): the provider and the executor are commands it is given.
- **Then the pipeline and one status command.** On top of that, a kernel lists a project's obligations through its provider, plans what has no current result, sends the rest to the site's executor, records verdicts in the ledger, and answers one status command an agent can run on a project. That replaces `tools/host.py` and `tools/status.py` in CI, and they become references only.
- **The site stays outside.** How a site runs work, and how it decides that a batch of work ended well, is the site's executor, kept in its own binding (decision 0023). The kernel requires of any executor that each report says how a run ended, on what platform and with which tools, and treats any run that did not exit, or ran something other than it was asked to, as no result.

## Consequences

- The host rules are judged in two independent kernels as well as in the reference, and a change to them changes the kit first.
- The stage-0 helpers `tools/provider_host.py` and `tools/host.py check` are not deleted when a kernel can do their job, as decisions 0023 and 0026 had it: they stay as references the kit is checked against, so a kit expectation is never taken from a kernel.
- Delivered in two steps: the session and the check first; the pipeline and the status command after.
- The judges of both kernels as hosts are in CI and in the planted-defect suites before either kernel implements them, so both are red until the kernels do: a check is written before the code it judges (AGENTS.md rule 3).

## What would show this wrong

- A case added to the kit on which a kernel and the reference give different answers, while both pass every case already there, shows the rules not written down exactly.
- A site that cannot express its executor as a command the kernel is given shows the executor interface too narrow.
