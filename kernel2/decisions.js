'use strict';
// A decision flagged when what it governs changes (conformance/README.md, decisions scenarios).

// True exactly when the content behind the governed name is not the content the
// decision recorded. A name that no longer exists has no content, so it is flagged.
function isFlagged(names, governs, recorded) {
  const now = names.has(governs) ? names.get(governs) : null;
  return now !== recorded;
}

function runScenario(scenario) {
  const names = new Map(Object.entries(scenario.names));
  let recorded = names.has(scenario.governs) ? names.get(scenario.governs) : null;
  const results = [];
  for (const { do: step } of scenario.steps) {
    if (step.edit) {
      if (step.edit.to === null) names.delete(step.edit.name);
      else names.set(step.edit.name, step.edit.to);
    } else if (step.review) {
      if (names.has(scenario.governs)) recorded = names.get(scenario.governs);
    }
    results.push({ flagged: isFlagged(names, scenario.governs, recorded) });
  }
  return results;
}

module.exports = { isFlagged, runScenario };
