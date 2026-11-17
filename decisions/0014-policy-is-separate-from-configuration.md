---
id: "0014"
title: Policy is separate from configuration
status: proposed
date: 2026-11-17
governs:
  - MODEL.md
  - dodona.toml
supersedes: []
---

# 0014. Policy is separate from configuration

## Context

dodona's user is an agent, and an agent asked to make a project pass can do it honestly and uselessly: lower a bound, delete an obligation, bind a weaker checker, choose a looser reproducibility level. Every resulting record is valid, and the result is green.

## Decision

What must pass is stated in a **policy**, separate from the configuration the working agent edits. Policy names the required obligations, the minimum evidence class, minimum bounds, whether non-vacuity must be shown, the isolation level required, and the providers, executors and record origins that are acceptable.

Project status is always reported relative to a policy, with that policy's identity. The kernel also compares the policy in force with a **reference policy**, by default the one on the project's main line, and reports any difference as a separate, prominent result. A change that weakens policy is therefore never invisible inside an otherwise passing report.

How policy is protected from the agent it constrains is not settled: candidates are a signature by the owner, a separate repository, or mandatory review of policy changes.

## Consequences

- "Passed" always means "passed against this named bar".
- A project with no policy reports `nothing-required`, never a pass.
- Until protection is settled, write access to policy is part of the trusted base and is listed as such.

## Alternatives rejected

- Trust the agent's instructions: an instruction is not a mechanism.
- Put the requirements in configuration: the agent being judged would own the bar.

## What would show this wrong

An agent can move a project from not passing to passing by editing only files it controls, and the report does not show that the bar moved.
