---
id: "0027"
title: Vouching for an act is a keyed check value under a key policy lists, policy is read from the protected branch, and nothing vouches yet
status: proposed
date: 2026-11-17
governs:
  - tools/attest.py
  - protocol/act-record.schema.json
  - policy.toml
supersedes: []
---

# 0027. Vouching for an act is a keyed check value under a key policy lists, policy is read from the protected branch, and nothing vouches yet

## Context

[0024](0024-separation-is-graded-not-enforced.md) grades how separate a checker was and caps a bare claim at `helper`. Anything higher needs the facts vouched for by something the working agent does not control. That decision did not say how, so the levels above `helper` were words.

## Decision

**The mechanism.** A harness vouches for named fields of an act record with HMAC-SHA256, under a key, over the canonical encoding of the list of covered fields and their values. Policy lists the keys that count, by name. A kernel recomputes the value. A fact is vouched for only if every field it reads is covered, the key is one policy lists and the value matches; a level is granted only if every fact of that level and of the levels below is vouched for. It is a shared-key value and not a signature: whoever can check it could have made it.

**Why a shared key.** The seed kernels use only their language's standard library, and neither has public-key signatures in it. A keyed hash can be written in a page and tested against published vectors. The price is that the kernel must hold the key, so the kernel must also be out of the working agent's reach wherever a higher grade is to mean anything. `credentialed`, which needs a real signature, stays unavailable.

**The policy anchor.** The keys that count, and the floors acts must meet, are in the policy. If the working agent can edit the policy it can list its own key. So status reads the policy from the protected reference branch, says so, and says loudly when it could not and fell back to the working copy.

**What exists.** `tools/attest.py` computes and checks the value. Both kernels verify it, against values written into the kit and against values made fresh at test time. That is the mechanism, tested with a key that is published in the kit and worth nothing.

**What does not exist.** A harness. Something has to hold a key the working agent cannot read, start the checker itself, hand it the brief and the material, keep the transcript, and sign only what it saw. `tools/attest.py` does none of that: it signs whatever record it is given. Used by the working agent on its own records it would turn every claim into an attested one, so it is not used on dodona's own records, and dodona's policy lists no key.

## Consequences

- The highest grade anything in this repository can earn is still `helper`. The status of dodona itself shows `self` for every act, because no act record exists.
- An agent that controls the machine a kernel runs on can read the key and defeat this. Separation by a shared key is worth what the separation of the machines is worth.
- A project that wants higher grades today has to build the harness: a service or a CI job with a secret the agent's session cannot read. The kit tells it exactly what its kernel will accept.
- Best practice stays what it was: whoever grants an exception or confirms a baseline should not be the party whose work is judged, and a reader should treat `helper (claims apart)` as a claim.

## What would show this wrong

- A record graded above `helper` whose check value was made by the agent whose work it judges.
- A kernel accepting a value under a key the protected policy does not list, or one that does not match.
- A status that used a policy from the working copy without saying so.
- Any record about dodona's own work carrying a check value while no harness exists.
