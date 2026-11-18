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

**The value binds what was judged.** A review found that the first version vouched for who checked and how, and not for what: a signed refusal could be copied as an agreement, or onto another target, and still count. So nothing above `helper` is granted unless the covered fields also include the kind of act, its target, its result and what it belongs to. A key in policy that is not a real key vouches for nothing, and a record that is not well formed is graded `self`.

**Why a shared key.** The seed kernels use only their language's standard library, and neither has public-key signatures in it. A keyed hash can be written in a page and tested against published vectors. The price is that the kernel must hold the key, so the kernel must also be out of the working agent's reach wherever a higher grade is to mean anything. `credentialed`, which needs a real signature, stays unavailable.

**The policy anchor.** The keys that count, and the floors acts must meet, are in the policy. If the working agent can edit the policy it can list its own key. So status reads the policy from the protected reference branch, says so, and says loudly when it could not and fell back to the working copy.

**What exists.** `tools/attest.py` computes and checks the value. Both kernels verify it, against values written into the kit and against values made fresh at test time. That is the mechanism, tested with a key that is published in the kit and worth nothing.

**A reference harness.** `tools/harness.py` does what a harness must: it makes an empty directory with only the named material, starts the checker itself there with an almost empty environment, runs it first on a known-wrong and a known-right case, keeps everything the checker printed, and signs the record of what it did. `tools/run_harness_check.py` runs it on a real small checker and on one that agrees with everything; both kernels grade the first `tested` or `cross-make` and see through the second.

**What does not exist.** A harness out of the working agent's reach. The reference reads its key from a file, so whoever can read the file can sign anything; and it takes on the caller's word who the worker is, who wrote the brief, who supplied the known cases and which make of model each side is. Run by the working agent on its own work it would turn every claim into an attested one. So it is not used on dodona's own records, and dodona's policy lists no key.

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
