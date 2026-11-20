---
id: "0035"
title: A second provider runs a project's tests, one obligation per test, through the same protocol as the model checker
status: proposed
date: 2026-11-20
governs:
  - providers/node-test/
  - dodona.toml
supersedes: []
amends: []
---

# 0035. A second provider runs a project's tests, one obligation per test, through the same protocol as the model checker

## Context

The only provider that checks anything is the model checker's ([issue 19](https://github.com/sloik/dodona/issues/19)). A protocol shaped by one provider can hide assumptions that only a second, different provider would show. Examples are a run that reads one folder, a verdict read from a tool's own words, and a strength that means "every state within bounds". dodona has test suites of its own, and the Node runtime's built-in test runner is the cheapest of them to drive: the second kernel's tests in `kernel2/test.js` are 48 top-level `test(...)` calls with literal names, and need nothing but Node and the kernel scenarios they read.

## Decision

- **A provider for Node's test runner, `dodona.node-test`, in `providers/node-test/`.** It offers `obligation.enumerate` and `obligation.check`, and never runs a test itself: like the model checker's provider, it describes runs and reads what they printed.
- **One obligation per top-level test with a literal name.** A file the binding gives that is named `test.js` or ends in `.test.js` is a test file. Every `test('name', ...)` call at the start of a line whose name is one string literal (escapes only `\'`, `\"`, `\\`) is a test. The obligation is named `<file>::<name>`, with `expect: "holds"`. A test named otherwise, a name holding `#` or `\` (which the runner's output escapes), an empty name, or a name used twice in a file (neither copy) is rejected with a reason, never guessed at. Nested tests are part of their top-level test.
- **What a check reads.** Every file the binding gives: a test may read any of them (one of the second kernel's tests reads the kernel scenarios in `conformance/kernel/`). So any change to a file the binding claims changes every test's key, and all are run again; that is the price of not knowing what a test reads. A test that reads a file outside its binding fails or errs for want of it; a failure caused that way is indistinguishable from a real one, so the binding must claim everything its tests read.
- **The run.** `node --test --test-reporter=tap --test-name-pattern=<the name, as an anchored, escaped pattern> <file>`, in the project root, with tool `node` and a wall limit of two minutes.
- **The verdict.** It is read from the TAP lines at the top level (not indented) and the exit status together. Node reports a file whose pattern matched no test as one passing test named after the file, so the counts it prints can pass a test that does not exist; they are not read.
  - exactly one top-level line, `ok N - <this test's name>`, and exit status 0 → `passed`;
  - exactly one top-level line, `not ok N - <this test's name>`, and exit status 1 → `failed`;
  - anything else (no line, another name, more than one, a `# SKIP` or `# TODO` directive, a line and an exit status that disagree) → `error`.
- **Strength.** Class `test`, rank `sampled`: a test shows the property on the examples it runs, no more. A project whose policy asks for `bounded` or stronger is not satisfied by tests alone.
- **Tool.** `node` is pinned at the site by a version floor, as Java is: the site records the build it ran.
- **Where the runs go.** Test runs need no model checker, so this site runs them on a hosted CI machine, not on the shared queue, which is for TLA+ work. The kernel sees one executor command per run, as decision 0034 says; each of this site's executors runs the tools it has and answers `unavailable` for a run of any other tool, which is never recorded. So the model checks run where the queue is, the tests run where Node is, and each run of the kernel reuses what the other recorded in the ledger they share.

## What would show this wrong

- A test whose verdict differs when it runs alone from when the whole file runs shows that running each test by name changes what is checked.
- A Node release that reports a skipped, filtered or crashed test with a top-level `ok` line naming it shows the verdict rule too trusting.
- A provider of another kind (a compiler, a proof assistant) that needs something this one did not (outputs, more than one run, inputs it learns while running) shows what the protocol still takes from the model checker.

## What this does not do

- Only top-level tests with literal names become obligations; tests made in loops, or named from variables, are rejected and stay unchecked.
- A test is run alone, by name. A test that passes only after another one ran first fails or errs here, by design.
- Node's runner matches the name pattern against nested tests as well; a nested test with the same name as a top-level one would run too and make the check an error.
- Isolation is best-effort: the CI executor runs tests in a folder holding only their inputs, not in a sandbox.
- It does not read the first kernel's Rust tests; `cargo test` compiles the crate on every run, and that waits for a provider that can share a build between checks.
