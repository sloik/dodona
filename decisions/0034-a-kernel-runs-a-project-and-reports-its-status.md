---
id: "0034"
title: A kernel runs a project's checks and reports its status, from what providers and a batch executor tell it
status: proposed
date: 2026-11-19
governs:
  - kernel/
  - kernel2/
  - protocol/messages.schema.json
  - conformance/README.md
supersedes: []
amends:
  - "0033"
  - "0026"
---

# 0034. A kernel runs a project's checks and reports its status, from what providers and a batch executor tell it

## Context

[Decision 0033](0033-a-kernel-hosts-providers.md) has each kernel host a provider session and take one check to a verdict. Its second step is the pipeline: list a project's obligations, plan what has no current result, send the rest to the site's executor, record verdicts in the ledger, and answer one status command an agent can run. Today `tools/host.py plan`, `collect` and `conclude`, `tools/keep.py` and `tools/status.py` do this in CI, and they know things no kernel may know:

- **Which files a check depends on.** The helper takes every file under a folder the model-checker provider names in the obligation's `config`. That field is the provider's own invention, so this does not carry over to any other provider.
- **Where obligations and intents come from.** The helper lists `spec/*/*` itself, under a binding name it writes in by hand, and reads `intents/*.md` with a tool of its own.
- **How work reaches the site.** One batch job per CI run, which blocks until it ends; whether it ended well is decided from files the site's driver writes.
- **Which policy counts.** The policy is read from git as it is on `main`, so a change cannot loosen what it is judged by. A kernel cannot call git, and must not.

## Decision

- **A provider says what each obligation depends on.** `obligation.enumerate` answers each obligation with `inputs`: the paths of the files a check of it may read. The host takes those files and no others into the check, as it takes them now. A provider that lists too few files gets checks that cannot read what they need. That shows as an error, never as a pass, because a run may read only its declared inputs (host rule 9). The model-checker provider lists exactly the files the helper takes today, so every key covers the same files as before. The provider's code changes, and so does `tools/host.py`, and the key holds a digest of each, so every kept result (121 checks and the two lists of states) is run again once on the shared queue. Nothing is recorded as passed without a completed run.
- **Intents come from a provider too.** `intent.index` is served by a provider that reads `intents/*.md`. The kernel names no file format. The request gains the obligations every binding enumerated, by binding and name, so the provider answers each criterion with the obligations that check it (`links`), and the kernel matches no patterns. Each intent gains `text`, the intent as written, all of it, which is what an owner confirms, and `worker`, who does the work. A file the provider cannot read one way only is `rejected`, and a kernel gives no status while any intent file is rejected, as the stage-0 helper does today. The baseline an owner confirms is computed as the status rules in [conformance/README.md](../conformance/README.md) give it now, so it is the same whether a kernel or the helper reads the intents.
- **The project file says which provider does what.** `dodona.toml`'s bindings name a provider, the capabilities it serves and the files it claims, as [docs/configuration.md](../docs/configuration.md) describes. A kernel reads the subset the contract lists (the tables `[project]` and `[policy]`, the arrays of tables `[[binding]]`, `[[platform]]` and `[[tool]]`, values that are strings or lists of strings, and comments), and refuses a project file outside it. It does not guess. Every capability a binding lists that the command does not serve is listed in the report as not served, binding by binding, never dropped. How a provider is started is the site's: the caller gives, for each provider name, the command that starts it and the files that are its code. A command names an interpreter and a path on the site's machine, which the project file must not hold.
- **Work goes to the site as batches.** The executor is a command the kernel is given. It takes a list of runs and answers a report for each, plus whether the batch as a whole ended. A run with no report, or a batch that did not end, gives `unavailable` or `error`, never a pass. A check that asks for a second run gets it in a later batch, up to the limit of eight runs.
- **The caller supplies what only the site knows.** Beside the policy (below), the kernel is given the platform runs are made on, the tools as the site's lock gives them (name, version, digest), and a `runner` digest of what sends runs and judges reports at the site. A result's key holds the provider's version as `version+code+runner`: `code` is a digest the kernel makes of the provider's own files, which the site names (below), keyed by their paths from the project root, and `runner` is the site's. The stage-0 host keys its digest differently (paths within the provider's folder), so keys change once more when CI moves from it to a kernel. So a change to the provider's code or to the site's runner makes earlier results stop counting, whichever kernel reads them, and two kernels given the same input compute the same key.
- **The caller supplies the policy, anchored and reduced.** The site reads the policy from the protected branch, checks it against [policy.schema.json](../protocol/policy.schema.json) (a misspelt field is refused, never ignored), fills in the schema's default floors, and gives the kernel only what the status rules apply, with the paths of every other field the policy holds. The kernel names those in the report and never states a project `passed` or `nothing-required` while any is left: a field no rule applies could have failed it. Reading it from the protected branch, and saying so in the report, stays with the site's binding, which a kernel cannot replace. The status report says where the policy came from, as the caller stated it.
- **Two commands.** `status` reads the project, its ledgers and the policy, and prints one JSON report: the report the kit's status rules give today, with where the policy came from and where each intent tree's hard gates sit. [status.schema.json](../protocol/status.schema.json) describes more than any kernel gives (today's report differs from it in seven places), so it stays a target, as issue 24 records. The scenario judged ends with one step that names nothing, so a project with an empty ledger has a report too; the contract rules out an intent that step could name. It runs nothing. `run` plans, sends one batch at a time, records each verdict in the ledger and ends with the same report. It also gives the counts of checks run, reused and refused. Acts, of anyone, are read only from the owner's ledger in the repository, as today; nothing else is read from it.
- **Status first.** `status` is delivered before `run`, because it depends on less and the kit already judges most of what it reports.
- **Replayable.** The kit judges both commands from recorded provider answers and executor reports. The same recording can be replayed through both kernels and the reference, so their answers can be compared on inputs no case gives.

## Consequences

- The protocol gains `inputs` on each enumerated obligation. The model-checker provider and the conformance kit are changed first, before either kernel.
- The intents tool becomes a provider. The project file gains the binding for it.
- CI's model job calls a kernel's `run` and `status` in place of `tools/host.py` and `tools/status.py`. Those two stay as references the kit is checked against, as decision 0033 has it.
- The site's driver keeps deciding whether a batch ended, and says so in the reports it hands back. The kernel decides nothing about the site.
- The kit's expectations are written from this text and the reference, before either kernel implements them, and a separate reviewer attacks the contract, the reference and the cases before any kernel's author sees them.

## What would show this wrong

- A provider whose checks cannot be described by a fixed list of input files, such as one whose inputs depend on what an earlier run found, shows `inputs` too narrow.
- A site that cannot answer a batch with a report per run shows the batch interface too narrow.
- A key that a kernel computes differently from the stage-0 host on the same inputs, other than by `runner`, shows the key's description incomplete.
- A key whose files change for the model-checker provider when it starts listing `inputs` shows the listing is not the set the helper used. Keys that change only by the digests of the provider's code or of the runner do not.
