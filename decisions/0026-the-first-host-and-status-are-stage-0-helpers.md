---
id: "0026"
title: The first host and status command are stage-0 helpers, and a result is keyed by what was measured to have run
status: proposed
date: 2026-11-17
governs:
  - tools/host.py
  - tools/status.py
  - providers/tlc/
  - dodona.lock
supersedes: []
---

# 0026. The first host and status command are stage-0 helpers, and a result is keyed by what was measured to have run

## Context

A kernel could work out status from a scenario, and a model checker ran in CI, but the two had never met: no provider spoke the protocol for real, nothing was written to a ledger, and no status was derived for dodona itself. Joining them needs a program that starts a provider, has runs executed, and passes results to a kernel. The seed kernels do none of that ([0025](0025-the-first-seed-kernel.md)).

## Decision

**Where the host lives, for now.** `tools/host.py` and `tools/status.py` are stage-0 helpers in the sense of [0023](0023-stage-0-checks-run-in-ci-with-disposable-helpers.md): Python, standard library only, disposable. They decide nothing about status. The host carries messages and enforces the rules about them; every identity, every ledger line and every status comes from a kernel. When a kernel can host providers itself, these two files go.

**Two halves.** The host is split into `collect`, which needs the executor, and `conclude`, which needs a kernel, because in this repository's own CI they are different machines. Everything `collect` learned is saved as files, and `conclude` refuses a run whose description differs from the one that was executed.

**The first provider.** `providers/tlc/` drives the model checker dodona already used. It describes runs and interprets their output; it never starts anything. A configuration that must show a violation is a planted defect when a design configuration checks the property it breaks, and is otherwise a check that something can happen, which holds when the violation is found. One function reads the checker's output, shared with the older tool, so the two cannot disagree.

**A result is keyed by what was measured.** The executor measures the digest of each tool file it ran. The key of an evidence record is built from those measurements, not from what was asked for. Status builds the key it looks for from the lock. So a result made with a tool the lock does not pin, or pins differently, is in the ledger and never counts. A tool pinned differently from what was measured ends every run of the job as `tool-mismatch` before the provider is asked anything.

**The lock is a draft.** `dodona.lock` is written by hand, pins single files and not whole tool trees, and has no resolver behind it. The Java runtime is whatever the executor has; only its launcher file is measured, which says little about the runtime. This is stated in the file and in every record made while a tool is unpinned.

**Protocol changes this forced.** A run description may give the directory a program starts in, and may name a file of a tool in an argument as `${tool:NAME}/PATH`; a tool tree need not be placed in the working directory; a check request carries the link from a planted defect to what it must break. Three rules were added to those a schema cannot express, each with a case in `conformance/provider/check-cases.json`.

## Consequences

- dodona's own status is now worked out by a kernel in CI and published with each run. It is `draft` for every intent, because nobody has confirmed the criteria through an act a kernel can read, and the project is `unknown`. That is the honest answer, and making it better is the owner's act, not the agent's.
- Criteria are tied to obligations by a `checks` line in an intent's front matter. Only two criteria of one intent have one. The rest are checked by things that are not yet obligations.
- The host's rules are tested by a provider that breaks them one at a time. The host itself is not a kernel and passing these cases says nothing about a future kernel's host.
- Two stage-0 programs now sit between the provider and the kernel. Anything they get wrong is not caught by the conformance kit, which judges kernels.

## What would show this wrong

- A result recorded with one tool counting as evidence after the lock pins another.
- A provider that breaks a listed rule and still gets a verdict recorded as passed.
- The host working out a status, an identity or a ledger line itself instead of asking a kernel.
- The two halves disagreeing about what was run and a verdict being recorded anyway.
