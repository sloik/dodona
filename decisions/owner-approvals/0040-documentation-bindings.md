---
id: "PR 40"
title: A prior documentation rule approval names the exact change
status: proposed
direction: owner
governs:
  - tools/check_docs.py
  - tools/check_repo.py
  - docs/doc-map.toml
supersedes: []
---

# Owner decision for the documentation bindings in PR 40

## Context

The trusted documentation check deliberately fails whenever a pull request edits a binding in the documentation map. An owner can review the binding and merge over that failure. The red result still says the documentation judgment failed even after the policy decision has been made.

For PR 40, all existing paths keep their binding and every newly bound path has a document. The change adds three bindings and extends two existing bindings to new paths. Moving the bindings to a separate prerequisite would also move 35 files, including reference tools, fixtures and changes to the model provider and host. Landing it before PR 40 would invalidate 121 cached model results and two state dumps more than once. Updating PR 40 to incorporate the prerequisite would also restart its active checks and put stacked PR 49 behind it. [PR 40](https://github.com/sloik/dodona/pull/40) · [Owner-review result](https://github.com/sloik/dodona/actions/runs/44993613841/job/137119836974).

## Decision

An owner approval already recorded in the checker on protected `main` may satisfy the documentation map's rule-review requirement. The approval names the full pull request head, its merge base and the SHA-256 digests of the map before and after. It applies only while the map on `main` still matches that baseline and the protected record is accepted. Moving any of those inputs requires a new review. The check names the approval record beside the approved rule changes.

The approved input is the exact PR 40 head `6a381dca88a1fc2eddc3e214f238597c919ab732`, with merge base `32e8ce3fd216a512fa07799179ccf39c0d6b3bf7`. The before and after map digests are `dac6a5335a4592a2449403c78eaedae297762e4dcb58aed1629a38535442ac3f` and `ef5b836c07acde1006f9d1aec03115f1b575913791e42cc426558b616525ceac` respectively. Argo is the project owner and records this decision at separation `self`. The three subagent reviews informed the decision at separation `helper`.

The approval satisfies review of those map rules only. The same trusted job still enforces coverage, requires the affected documents, rejects new exemptions and known drift, judges protected checker changes, and validates the pull request description. The approval applies to an immutable pull request head. Working-tree judgments and author-controlled descriptions cannot supply approval. Ordinary rule changes still follow owner review.

## What would show this wrong

- A different head, merge base, or map receives the recorded approval.
- An exact approval makes a missing document, new exemption or protected checker change pass.
- The approved pull request passes with its documentation checks incomplete.
