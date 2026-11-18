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
  acts: require('./acts'),
  status: require('./status'),
};

// A step the runner could not take. It changes nothing and is answered with the
// result as things stand. This is a safety net: the runners already turn aside
// every step they understand to be out of turn or carrying a value not allowed.
const NO_STEP = { do: {} };

function runSafely(runner, scenario) {
  try {
    return runner.runScenario(scenario);
  } catch (error) {
    process.stderr.write(`kernel2: a step threw (${error.message}); stepping through the scenario one step at a time\n`);
    // Take the steps one at a time; a step that throws is dropped and answered
    // with the result of the steps kept before it.
    const kept = [];
    const results = [];
    for (const step of scenario.steps) {
      try {
        const answers = runner.runScenario({ ...scenario, steps: [...kept, step] });
        results.push(answers[answers.length - 1]);
        kept.push(step);
      } catch (stepError) {
        process.stderr.write(`kernel2: a step was dropped because it threw (${stepError.message})\n`);
        const current = runner.runScenario({ ...scenario, steps: [...kept, NO_STEP] });
        results.push(current[current.length - 1]);
      }
    }
    return results;
  }
}

// Returns { results: [...] }, or throws if the kind is not known.
function runScenario(scenario) {
  const runner = runners[scenario.kind];
  if (runner === undefined) throw new Error(`unknown scenario kind: ${scenario.kind}`);
  return { results: runSafely(runner, scenario) };
}

module.exports = { runScenario };
