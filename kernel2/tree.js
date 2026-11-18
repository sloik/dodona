'use strict';
// A parent intent with children (conformance/README.md, tree scenarios).

// Tree status. `root` and each of `children` is { gate, check }.
// The policy's floor is counted over the whole tree, root and every child, and
// every child must have a hard gate of its own; a child is not held to the
// policy's number on its own (decision 0030, decision 0017).
const vocabulary = require('./vocabulary');

// The gates a tree allows. Any other gate in an `edit` or an `add` changes nothing.
const TREE_GATES = ['hard', 'soft'];

function treeStatus(policy, confirmed, root, children) {
  const nodes = [root, ...children];
  const hard = nodes.filter((node) => node.gate === 'hard');
  const floor = Math.max(1, policy.min_hard_gates); // a floor below 1 is 1
  if (!confirmed) return 'draft';
  if (hard.length < floor) return 'unguarded';
  if (children.some((child) => child.gate !== 'hard')) return 'unguarded';
  if (hard.some((node) => node.check !== 'passed')) return 'open';
  return 'delivered';
}

function runScenario(scenario) {
  const root = { gate: scenario.root.gate, check: 'unknown' };
  const children = new Map();
  for (const [name, details] of Object.entries(scenario.children)) children.set(name, { gate: details.gate, check: 'unknown' });
  let confirmed = false;
  const nodeNamed = (name) => (name === 'root' ? root : children.get(name));
  const { isString } = vocabulary;
  const results = [];

  for (const { do: step } of scenario.steps) {
    if (step.confirm) {
      confirmed = true;
    } else if (step.check) {
      const node = nodeNamed(step.check.node);
      if (node && vocabulary.CHECKS.includes(step.check.status)) node.check = step.check.status;
    } else if (step.edit) {
      const node = nodeNamed(step.edit.node);
      if (node && TREE_GATES.includes(step.edit.to) && node.gate !== step.edit.to) {
        node.gate = step.edit.to;
        confirmed = false;
      }
    } else if (step.remove && isString(step.remove.child)) {
      if (children.delete(step.remove.child)) confirmed = false;
    } else if (step.add) {
      if (isString(step.add.child) && !children.has(step.add.child) && TREE_GATES.includes(step.add.gate)) {
        children.set(step.add.child, { gate: step.add.gate, check: 'unknown' });
        confirmed = false;
      }
    }
    results.push({ status: treeStatus(scenario.policy, confirmed, root, [...children.values()]) });
  }
  return results;
}

module.exports = { treeStatus, runScenario };
