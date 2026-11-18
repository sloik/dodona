'use strict';
// A decision flagged when what it governs changes (conformance/README.md, decisions scenarios).
// `recorded` maps each governed name to the content the decision recorded for it.

// True exactly when the content behind some governed name is not the content
// recorded for it. A name that no longer exists has no content (null).
function isFlagged(names, governs, recorded) {
  return governs.some((name) => {
    const now = names.has(name) ? names.get(name) : null;
    return now !== recorded.get(name);
  });
}

function runScenario(scenario) {
  const names = new Map(Object.entries(scenario.names));
  const recorded = new Map();
  for (const name of scenario.governs) recorded.set(name, names.has(name) ? names.get(name) : null);
  const results = [];
  for (const { do: step } of scenario.steps) {
    if (step.edit && Object.hasOwn(scenario.names, step.edit.name)) {
      if (step.edit.to === null) names.delete(step.edit.name);
      else names.set(step.edit.name, step.edit.to);
    } else if (step.review) {
      // A review needs every governed name to exist; it records what they are now.
      if (scenario.governs.every((name) => names.has(name))) {
        for (const name of scenario.governs) recorded.set(name, names.get(name));
      }
    }
    results.push({ flagged: isFlagged(names, scenario.governs, recorded) });
  }
  return results;
}

module.exports = { isFlagged, runScenario };
