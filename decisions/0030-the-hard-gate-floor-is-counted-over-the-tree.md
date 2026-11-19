---
id: "0030"
title: The hard-gate floor is counted over the whole tree, and every intent in it needs a hard gate
status: proposed
date: 2026-11-18
governs:
  - spec/tree/IntentTree.tla
  - conformance/README.md
supersedes: []
---

# 0030. The hard-gate floor is counted over the whole tree, and every intent in it needs a hard gate

## Context

Policy sets a floor: the fewest hard gates an intent may have and still be delivered. The data model says an intent with no hard gate anywhere in it or its descendants, or with fewer than policy demands, is unguarded. It also says, as decision 0017 does, that gate counts are totalled over all descendants, so moving a criterion into a child changes nothing in the total.

Read literally, the two sentences disagree once a child is an intent too. If each child were held to the policy's number on its own count, then with a floor of two a root with two hard gates is delivered, but move one of them into a child and the child counts one, is unguarded, and holds the tree back. Moving a criterion would then lose something, which decision 0017 rules out. Issue 27 found the tree model had left this undecided; a first repair held every child to the floor and was wrong for that reason.

## Decision

- The policy's number is counted over the whole tree: the root and every child, each child's own descendants included. A tree that counts fewer is unguarded. A floor below one counts as one.
- Every intent in the tree, each child included, must have at least one hard gate in it or its descendants. A child with none is unguarded, and so is the tree.
- A child is not held to the policy's number on its own.
- Where any intent in the tree is unguarded, the tree's status is `unguarded`; otherwise the rules for `open` and `delivered` apply as before.

## Owner direction and what was weighed

Four separate reviews, each from one standpoint (a less capable worker agent, a capable agent looking for the cheapest way to a delivered status, the owner who reads mostly the status word, and the design's maintainer), weighed this rule against holding every child to the policy's number, a per-child policy setting, and no per-child requirement. All four recommended this rule. They agreed that a count of hard gates cannot tell a real check from a trivial one: a stricter count mostly buys hard gates that cannot fail, punishes splitting work, and is still beaten by nesting. Their shared concern was that a child can be reported delivered on fewer hard gates of its own than the floor. On 2026-11-18 the owner chose this rule, with that made visible rather than forbidden.

So, in addition:

- The root of a tree is an intent with no parent. The floor is applied there and only there; each intent is counted once, however it is reached.
- What is reported shows where the gates are thin: the status report names, for each tree, the intent with the fewest hard gates of its own, and marks every child whose own count, with what is below it, is under the floor, saying the floor was met only over its tree. The owner's confirmation shows the same before the owner agrees.
- A per-child floor is not a policy setting yet. It becomes one when a project shows it needs it.

## A gate nobody can read in a tree

Trees, as the kernel conformance kit describes them, know two gates, `hard` and `soft`. A gate written as anything else (`Hard`, `Soft`, `deferred`, a stray character), at the start or in a change, counts as `hard`. A mistake in writing a gate can then only make delivery harder, as the status rules already say of an intent's criteria. Found when the two kernels read such a gate differently.

## Consequences

- The tree model checks this rule, and has a planted defect for the reading it rejects (each child held to the policy's number).
- The kernel conformance kit states it in its tree section and has a scenario in which a floor of two is met by a root and a child with one hard gate each.
- An intent that is not part of a tree is its own root, so nothing changes for it.
- Not done here: the tree model and the kit go one level deep, so a hard gate held only by a grandchild is not modelled or tested; whether an intent with no criteria and no children is allowed is not decided; and the coverage display is computed by the stage-0 status helper, not by a kernel. They are written on issue 32.

## What would show this wrong

- An owner who splits an intent into children and finds the tree reported delivered with a child whose criteria are all soft would show the second rule missing.
- A tree that loses its delivery when a hard criterion is moved, unchanged, from the root into a child would show the first rule broken.
- A project that needs each child held to the policy's number on its own would show the rule too weak for it; that would need a policy setting, not a change to this rule.
