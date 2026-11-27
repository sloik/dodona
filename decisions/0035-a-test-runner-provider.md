---
id: "0035"
title: A stock Node test supplies one sampled obligation per dedicated evidence file
status: proposed
date: 2026-11-27
governs:
  - providers/node-test/
  - dodona.toml
supersedes: []
amends: []
---

# 0035. A stock Node test supplies one sampled obligation per dedicated evidence file

## Context

The model checker's provider was the first to produce project evidence ([issue 19](https://github.com/sloik/dodona/issues/19)). A Node test checks an observed example instead of every state within a model's bounds. Running one dedicated test file checks whether a differently shaped tool can use the same declaration, execution, ledger and verdict contract.

## Decision

- **A provider for Node's test runner, `dodona.node-test`, in `providers/node-test/`.** It offers `obligation.enumerate` and `obligation.check`, and never runs a test itself: like the model checker's provider, it describes runs and reads what they printed.
- **One top-level test per evidence file.** A bound `test.js` or `*.test.js` can define one obligation. The provider looks for a `test(...)` call at the start of a line named by a plain string literal. The obligation uses `<file>::<name>` and expects the test to hold. Multiple declarations, unreadable names and nonliteral names refuse that file. A test may have multiple assertions and nested tests.
- **What a check reads.** Every file the binding gives: a test may read any of them (one of the second kernel's tests reads the kernel scenarios in `conformance/kernel/`). So any change to a file the binding claims changes every test's key, and all are run again; that is the price of not knowing what a test reads. A test that reads a file outside its binding fails or errs for want of it; a failure caused that way is indistinguishable from a real one, so the binding must claim everything its tests read.
- **The run.** Run `node --test --test-reporter=tap -- <file>` with the bound file as an operand. The name is part of the evidence identity and is checked in the report. The host applies its ordinary argument validation, tool floor and two-minute wall limit.
- **The verdict.** Read the unindented TAP result and the actual exit status together. An unexpected top-level test is an error even when Node exits successfully. Refuse a test name equal to its own file path because Node can report that label when no test ran.
  - exactly one top-level line, `ok N - <this test's name>`, and exit status 0 → `passed`;
  - exactly one top-level line, `not ok N - <this test's name>`, and exit status 1 → `failed`;
  - anything else (no line, another name, more than one, a `# SKIP` or `# TODO` directive, a line and an exit status that disagree) → `error`.
- **Strength.** Class `test`, rank `sampled`: a test shows the property on the examples it runs, no more. A project whose policy asks for `bounded` or stronger is not satisfied by tests alone.
- **Tool.** `node` is pinned at the site by a version floor, as Java is: the site records the build it ran.
- **Execution.** Use the configured executor for the Node tool. The kernel receives one executor command per run, as in decision 0034. A site's executor can refuse an unknown tool without appending evidence.

## What would show this wrong

- A file with an extra, skipped or unobserved test that still earns evidence for the named test would falsify the verdict rule.
- A Node release that reports a skipped, filtered or crashed test with a top-level `ok` line naming it shows the verdict rule too trusting.
- A provider of another kind (a compiler, a proof assistant) that needs something this one did not (outputs, more than one run, inputs it learns while running) shows what the protocol still takes from the model checker.

## What this does not do

- Only top-level tests with literal names become obligations; tests made in loops, or named from variables, are rejected and stay unchecked.
- Multiple top-level declarations in one file require separate evidence files.
- Isolation is best-effort: the CI executor runs tests in a folder holding only their inputs, not in a sandbox.
- It does not read the first kernel's Rust tests; `cargo test` compiles the crate on every run, and that waits for a provider that can share a build between checks.
