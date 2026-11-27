'use strict';
// A parent intent with children (conformance/README.md, tree scenarios).

// The floor applies at the root. Every child needs a hard gate in its subtree.
const vocabulary = require('./vocabulary');

// The gate a string in an `edit` or an `add` counts as: `soft` only if it is exactly
// `soft`; any other text (`Hard`, `deferred`, ...) counts as `hard`, so a mistake in
// writing a gate can only make delivery harder. A gate that is not a string is of the
// wrong type: null, and the step changes nothing.
function gateCountsAs(gate) {
  if (!vocabulary.isString(gate)) return null;
  return gate === 'soft' ? 'soft' : 'hard';
}

// A starting gate that is not a string makes the scenario invalid: it is refused
// whole, before any step (conformance/README.md, tree scenarios).
class InvalidScenario extends Error {}

function parentName(details) {
  const parent = details?.parent;
  if (parent === undefined) return 'root';
  return vocabulary.isString(parent) ? parent : null;
}

function readChildren(scenario) {
  const entries = scenario.children;
  if (entries === null || typeof entries !== 'object' || Array.isArray(entries)) {
    throw new InvalidScenario('tree children must be an object');
  }
  const children = new Map();
  for (const [name, details] of Object.entries(entries)) {
    const gate = gateCountsAs(details?.gate);
    children.set(name, { parent: parentName(details), gate, check: 'unknown' });
  }
  return children;
}

function childLinks(children) {
  const links = new Map();
  for (const [name, child] of children) {
    if (!links.has(child.parent)) links.set(child.parent, []);
    links.get(child.parent).push(name);
  }
  return links;
}

function subtree(name, links) {
  const names = [name];
  for (const parent of names) {
    for (const child of links.get(parent) || []) names.push(child);
  }
  return names;
}

function validate(scenario) {
  const children = readChildren(scenario);
  if (gateCountsAs(scenario.root?.gate) === null || [...children.values()].some((child) => child.gate === null)) {
    throw new InvalidScenario('a starting gate in a tree is not a string');
  }
  if (children.has('root')) throw new InvalidScenario('a child cannot be named root');
  if ([...children.values()].some((child) => child.parent === null)) throw new InvalidScenario('a tree parent is not a string');
  if (subtree('root', childLinks(children)).length !== children.size + 1) {
    throw new InvalidScenario('every child must have a parent chain ending at root');
  }
}

function treeStatus(policy, confirmed, root, children) {
  if (!confirmed) return 'draft';
  const floor = Math.max(1, policy.min_hard_gates);
  const hard = [root, ...children.values()].filter((node) => node.gate === 'hard');
  const counts = new Map([['root', Number(root.gate === 'hard')]]);
  for (const [name, child] of children) counts.set(name, Number(child.gate === 'hard'));
  const names = subtree('root', childLinks(children));
  for (let i = names.length - 1; i > 0; i -= 1) {
    const name = names[i];
    const parent = children.get(name).parent;
    counts.set(parent, counts.get(parent) + counts.get(name));
  }
  const treeHard = counts.get('root');
  if (treeHard < floor) return 'unguarded';
  if ([...children.keys()].some((name) => counts.get(name) === 0)) return 'unguarded';
  if (hard.some((node) => node.check !== 'passed')) return 'open';
  return 'delivered';
}

function removeBranch(children, name) {
  if (!children.has(name)) return false;
  for (const node of subtree(name, childLinks(children))) children.delete(node);
  return true;
}

function runScenario(scenario) {
  const root = { gate: gateCountsAs(scenario.root.gate), check: 'unknown' };
  const children = readChildren(scenario);
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
      const gate = gateCountsAs(step.edit.to);
      if (node && gate !== null && node.gate !== gate) {
        node.gate = gate;
        confirmed = false;
      }
    } else if (step.remove && isString(step.remove.child)) {
      if (removeBranch(children, step.remove.child)) confirmed = false;
    } else if (step.add) {
      const gate = gateCountsAs(step.add.gate);
      const parent = parentName(step.add);
      const name = step.add.child;
      if (isString(name) && name !== 'root' && !children.has(name) && gate !== null
          && (parent === 'root' || children.has(parent))) {
        children.set(name, { parent, gate, check: 'unknown' });
        confirmed = false;
      }
    }
    results.push({ status: treeStatus(scenario.policy, confirmed, root, children) });
  }
  return results;
}

module.exports = { InvalidScenario, validate, gateCountsAs, treeStatus, runScenario };
