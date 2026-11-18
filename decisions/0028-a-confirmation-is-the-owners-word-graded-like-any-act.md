---
id: "0028"
title: A confirmation is the owner's word, graded like any other act, and kept in the repository
status: proposed
direction: owner
date: 2026-11-18
governs:
  - tools/confirm.py
  - records/
supersedes: []
---

# 0028. A confirmation is the owner's word, graded like any other act, and kept in the repository

## Context

An intent stays `draft` until its owner confirms that the criteria and gates are what was meant ([0017](0017-intent-in-plain-words-broken-down.md)). Nothing could record that, so nothing in dodona could ever leave `draft`. The simplest way to record it is a command the owner runs. But a command proves nothing about who ran it: an agent with access to the owner's machine could run it and commit the result.

The owner's view, 2026-11-18: this is a somewhat artificial case, because the users of dodona are agents, soon each on its own machine, and the owner of an intent may itself be an agent. It is still worth writing down and deciding.

## Decision

**A confirmation is an act record like any other.** `tools/confirm.py` shows the owner the criteria, gates and checks exactly as a kernel sees them, and on a typed confirmation adds one entry naming the baseline, a hash of exactly those things. It stops counting the moment any of them changes. It says the criteria are right. It does not say the work is done.

**It is graded, not trusted.** Nothing vouches for who typed it, so a kernel grades it `helper`: someone other than the worker says so. It counts only while the project's policy sets the floor for confirmations at `helper` or below. dodona's own policy does. The grade is shown beside the status, so a reader always sees how much stands behind a confirmation.

**The way to tighten it already exists and is not used yet.** A project that wants more raises the floor to `apart`. Then only a confirmation vouched for by a harness the worker cannot reach counts ([0027](0027-vouching-is-a-keyed-check-value-and-nothing-vouches-yet.md)). No such harness exists, so raising the floor today would mean no intent could ever leave `draft`. It is not raised.

**Confirmations live in the repository.** They are appended to `records/owner.ledger`, which is committed. Every confirmation is therefore a change someone can see before it reaches the protected branch, and that review is the real safeguard today. Results of checks stay out of the repository; they are produced by runs.

**The owner's ledger holds acts only.** Anything else written there, a result for instance, is not read: a result counts only when a run produced it.

**What the owner sees is what is read.** An intent's criteria are data, one line of JSON in its front matter, and nothing else is read. The table a person sees is written from that line by `tools/intents.py`, and a file is refused if the table differs, or if it holds anything else that could be taken for criteria: another table, an HTML table, a code block, a blockquote or a hidden comment. Two reviews found that a free-form table could always be written so that a person and the reader saw different things (a row numbered `2.`, a blank first cell, reordered columns, a table in a quote); the format no longer allows the choice.

**Only the owner's ledger counts.** A confirmation is read only from `records/owner.ledger`. An act found in any other ledger, such as the one CI keeps, is not read at all, so an agent cannot confirm by writing to a ledger it controls. A review showed that the first version counted one from anywhere.

**An agent does not confirm for the owner.** The command refuses to run without a terminal. That stops accidents and nothing else: a program can give it a terminal, and a review did. The safeguard that does work is that the owner's ledger is a reviewed, committed file.

## Consequences

- Intents in this repository can leave `draft` once their owner runs the command. Until then every status stays `draft`, and that is correct.
- An agent that controls the owner's machine and can push to the protected branch can forge a confirmation. dodona does not prevent it. It grades the act `helper` and leaves the trace in the history.
- Where the owner is itself an agent, the same holds one level up: what matters is that the confirmer is not the worker, and the grade says how separate it was.
- A stronger confirmation waits for a harness out of the worker's reach ([issue 26](https://github.com/sloik/dodona/issues/26)).

## What would show this wrong

- A confirmation counting after a criterion, a gate or a check behind it was changed.
- A confirmation by the worker, or by anyone who is not the owner, moving an intent out of `draft`.
- A status shown without the grade of the confirmation behind it.
- Projects routinely needing more than `helper` before a harness exists, which would mean the floor is a formality.
