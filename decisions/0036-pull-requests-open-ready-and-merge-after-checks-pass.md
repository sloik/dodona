---
id: "0036"
title: Reviewable pull requests open ready and merge automatically once their checks pass
status: proposed
direction: owner
date: 2026-11-21
governs:
  - AGENTS.md
  - .github/pull_request_template.md
  - .github/workflows/checks.yml
  - .github/workflows/docs.yml
  - .github/workflows/metrics.yml
supersedes: []
---

# 0036. Reviewable pull requests open ready and merge automatically once their checks pass

## Context

As of 21 November 2026, GitHub auto-merge is disabled. The `main` ruleset requires the three regular platform checks and both planted-defect checks. The trusted documentation and metrics judgments also need to be enforced before automation is enabled. [Main rules](https://api.github.com/repos/sloik/dodona/rules/branches/main) · [Documentation gate](../docs/gap-checks.md#a-change-must-bring-its-documents) · [Metrics gate](../docs/metrics.md).

## Decision

- Reviewable ordinary first-party pull requests to `main` open ready for review and use the existing evidence sections. [Pull request template](../.github/pull_request_template.md).
- Automatic merge requires genuine completed success from the expected workflow for each required check on the current pull request head. Both trusted judgments, `documents follow code (judged by main)` and `metrics only go up (judged by main)`, are mandatory. Required reviews and branch protections apply, and automation has no bypass permission. A new head needs fresh results. Skipped and neutral conclusions are insufficient. [Repository rules](../AGENTS.md) · [GitHub status checks](https://docs.github.com/en/pull-requests/reference/status-checks).
- Changes to what is judged and exceptions to those rules remain with the owner. The owner records any exception through the existing process. Implementation, rollout, and applying this policy to already-open pull requests are separate owner decisions. [Decision 0020](0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md) · [Owner review of judgment changes](../docs/gap-checks.md#a-change-must-bring-its-documents).

## What would show this wrong

- An ordinary, reviewable first-party pull request opens as a draft, or a mergeable ordinary pull request stays open after all genuine required successes and reviews while automation is active.
- A pull request merges automatically after green test jobs and a failed or missing trusted judgment.
- Automatic merge accepts a success for a previous head, a same-named result from another workflow, or a required result that was skipped or neutral.
- A change to what is judged or an exception goes through the ordinary automatic path.
