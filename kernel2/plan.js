'use strict';
// What is planned to run (conformance/README.md, plan scenarios).
//
// An obligation's inputs are the content of its targets and of everything they
// depend on, however indirectly, plus its tool. An obligation that is
// `artifact_of` another also has that other obligation's inputs. A result is
// kept for the inputs it was run on.

// The definitions a list of targets depends on, the targets included.
function reachable(definitions, targets) {
  const seen = new Set();
  const pending = [...targets];
  while (pending.length > 0) {
    const name = pending.pop();
    if (seen.has(name)) continue;
    seen.add(name);
    pending.push(...definitions[name].depends_on);
  }
  return [...seen].sort();
}

// What stands for the content of a definition: its own content, or with
// file-level identity the content of every definition in the same file.
function identityOf(scenario, content, name) {
  if (scenario.granularity !== 'file') return content[name];
  const file = scenario.definitions[name].file;
  const members = Object.keys(scenario.definitions).filter((other) => scenario.definitions[other].file === file).sort();
  return members.map((member) => [member, content[member]]);
}

// The inputs of an obligation as a list of [label, value] pairs.
function inputsOf(scenario, state, obligation) {
  const details = scenario.obligations[obligation];
  const inputs = [];
  if (details.artifact_of !== undefined) inputs.push(...inputsOf(scenario, state, details.artifact_of));
  if (details.targets !== undefined) {
    for (const name of reachable(scenario.definitions, details.targets)) {
      inputs.push([`definition:${name}`, identityOf(scenario, state.content, name)]);
    }
  }
  if (details.tool !== undefined) inputs.push([`tool:${details.tool}`, state.tools[details.tool]]);
  return inputs;
}

function keyOf(scenario, state, obligation) {
  return JSON.stringify([obligation, inputsOf(scenario, state, obligation)]);
}

function hasResult(scenario, state, results, obligation) {
  return results.has(keyOf(scenario, state, obligation));
}

// The obligations with no result for their current inputs, sorted.
function plannedNow(scenario, state, results) {
  return Object.keys(scenario.obligations)
    .filter((obligation) => !hasResult(scenario, state, results, obligation))
    .sort();
}

// Runs a plan scenario. Returns the list of results, one per step.
function runScenario(scenario) {
  const state = { content: { ...scenario.start.content }, tools: { ...scenario.start.tools } };
  const results = new Set();
  const answers = [];

  for (const { do: step } of scenario.steps) {
    let ran = null;
    if (step.edit) {
      state.content[step.edit.definition] = step.edit.to;
    } else if (step.repin) {
      state.tools[step.repin.tool] = step.repin.to;
    } else if (step.run) {
      const obligation = step.run.obligation;
      const source = scenario.obligations[obligation].artifact_of;
      const planned = !hasResult(scenario, state, results, obligation);
      const sourceReady = source === undefined || hasResult(scenario, state, results, source);
      ran = planned && sourceReady;
      if (ran) results.add(keyOf(scenario, state, obligation));
    }
    const answer = { plan: plannedNow(scenario, state, results) };
    if (ran !== null) answer.ran = ran;
    answers.push(answer);
  }
  return answers;
}

module.exports = { reachable, runScenario };
