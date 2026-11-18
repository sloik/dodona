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

## Consequences

- The tree model checks this rule, and has a planted defect for the reading it rejects (each child held to the policy's number).
- The kernel conformance kit states it in its tree section and has a scenario in which a floor of two is met by a root and a child with one hard gate each.
- An intent that is not part of a tree is its own root, so nothing changes for it.

## What would show this wrong

- An owner who splits an intent into children and finds the tree reported delivered with a child whose criteria are all soft would show the second rule missing.
- A tree that loses its delivery when a hard criterion is moved, unchanged, from the root into a child would show the first rule broken.
- A project that needs each child held to the policy's number on its own would show the rule too weak for it; that would need a policy setting, not a change to this rule.
