'use strict';
// Chooses the right runner for a scenario, by its kind.

const runners = {
  evidence: require('./evidence'),
  intent: require('./intent'),
  plan: require('./plan'),
  assurance: require('./assurance'),
  tree: require('./tree'),
  attempts: require('./attempts'),
  platforms: require('./platforms'),
  decisions: require('./decisions'),
};

// Returns { results: [...] }, or throws if the kind is not known.
function runScenario(scenario) {
  const runner = runners[scenario.kind];
  if (runner === undefined) throw new Error(`unknown scenario kind: ${scenario.kind}`);
  return { results: runner.runScenario(scenario) };
}

module.exports = { runScenario };
