---
id: "0032"
title: A stand-in is verified for its own key, and any disagreement about that key withdraws it
status: proposed
date: 2026-11-18
governs:
  - spec/platforms/Platforms.tla
  - conformance/README.md
supersedes: []
amends:
  - "0008"
---

# 0032. A stand-in is verified for its own key, and any disagreement about that key withdraws it

## Context

A result from one platform may stand in for another only when the provider's claim of platform independence has been verified (decision 0008). The architecture and the data model say what verified means: the same core key checked on at least two platforms with agreeing results. Decision 0008 says only "once the claim has been checked on two". The platforms model had decided verification once for every key, so one key that agreed on two platforms let another key's single record stand in. Issue 27 found this, and the repair follows the architecture and the data model.

Two further points were not written anywhere. A platform can record both verdicts for the same key, if a check is run twice and its results differ. And three platforms can split, two agreeing and one not.

## Decision

- Verification is decided for each core key on its own. Another key agreeing verifies nothing about this one.
- A key is verified when it has the same verdict on at least two platforms and no platform has recorded the other verdict for it, the platform being asked about and a platform disagreeing with itself included.
- So any disagreement about a key withdraws its stand-ins, even where two other platforms agree. This is stricter than "at least two platforms with agreeing results" read alone. It follows decision 0008's rule that a disagreement is a failure of reproducibility: a key that does not reproduce is not one whose results may be carried across platforms.
- A platform that has recorded both verdicts for a key has the status `conflict` for it.

## Consequences

- The platforms model checks this rule, with planted defects for verification decided across keys, for a platform's own disagreement ignored, and for only the latest verdict being kept.
- The kernel conformance kit states it in its platforms section, and both kernels implement it.

## What would show this wrong

- A project with many platforms where one flaky platform routinely withdraws every stand-in would show the rule too strict for it; that would need a policy setting, not a weaker default.
- A stand-in reported for a key that disagrees anywhere would show the rule not applied.
