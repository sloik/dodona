---
id: "0039"
title: Tree scenarios name a parent for each branch below the root
status: proposed
direction: owner
date: 2026-11-27
governs:
  - MODEL.md
  - conformance/README.md
  - spec/tree-depth/GrandchildTree.tla
supersedes: []
---

# 0039. Tree scenarios name a parent for each branch below the root

## Context

[Decision 0030](0030-the-hard-gate-floor-is-counted-over-the-tree.md) counts hard gates at every depth. The tree scenario format needed a way to identify which intent owns a grandchild while keeping a unique name for every node. The existing `children` map can identify nodes at any depth. Each entry can name its `parent`. An omitted parent means `root`, preserving the meaning of existing inputs.

## Decision

Every initial parent chain must end at `root`. A missing target, a non-string parent, a cycle or a child named `root` makes the whole initial scenario invalid. An `add` step accepts an optional parent and has an effect only when the parent exists and the new name is unused. A `remove` step removes the named child and its descendants. Each successful shape change requires confirmation again. Every intent draws hard gates from its own subtree, and every hard check can affect the result.

A project may use an intent with no criteria and no children. Its zero hard gates make it `unguarded` after confirmation. The status scenario for an empty intent exercises that rule.

## What would show this wrong

- The root omits a grandchild's hard gate, or a soft ancestor still counts as unguarded when it has a hard grandchild.
- Editing the grandchild's gate keeps the old confirmation, or a failed check at depth two leaves the tree delivered.
- A removed branch keeps evidence that a new node can inherit when it reuses a name.
