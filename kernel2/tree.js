'use strict';
// A parent intent with children (conformance/README.md, tree scenarios).

// Tree status. `nodes` is the root and every child as { gate, check };
// `children` is the children only.
const vocabulary = require('./vocabulary');

function treeStatus(policy, confirmed, root, children) {
  const nodes = [root, ...children];
  const hard = nodes.filter((node) => node.gate === 'hard');
  if (!confirmed) return 'draft';
  if (hard.length < policy.min_hard_gates) return 'unguarded';
  if (hard.some((node) => node.check !== 'passed')) return 'open';
  if (children.some((child) => child.gate !== 'hard')) return 'open';
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
      if (node && vocabulary.GATES.includes(step.edit.to) && node.gate !== step.edit.to) {
        node.gate = step.edit.to;
        confirmed = false;
      }
    } else if (step.remove && isString(step.remove.child)) {
      if (children.delete(step.remove.child)) confirmed = false;
    } else if (step.add) {
      if (isString(step.add.child) && !children.has(step.add.child) && vocabulary.GATES.includes(step.add.gate)) {
        children.set(step.add.child, { gate: step.add.gate, check: 'unknown' });
        confirmed = false;
      }
    }
    results.push({ status: treeStatus(scenario.policy, confirmed, root, [...children.values()]) });
  }
  return results;
}

module.exports = { treeStatus, runScenario };
