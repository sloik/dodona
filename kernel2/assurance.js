'use strict';
// The shown level and non-vacuity (conformance/README.md, assurance scenarios).

const SCALE = ['none', 'asserted', 'observed', 'sampled', 'bounded', 'proven'];
const LINKS = ['spec-to-code', 'code-to-runs', 'runs-to-world'];

// A link that is absent, null or not on the scale counts as `none`.
function levelOf(links, link) {
  const index = SCALE.indexOf(links[link]);
  return index < 0 ? 0 : index;
}

// The weakest of the three links.
function shownLevel(links) {
  return SCALE[Math.min(...LINKS.map((link) => levelOf(links, link)))];
}

// `none-planted`, `shown` or `not-shown`.
function nonVacuous(defects) {
  const statuses = Object.values(defects);
  if (statuses.length === 0) return 'none-planted';
  return statuses.every((status) => status === 'passed') ? 'shown' : 'not-shown';
}

function runScenario(scenario) {
  return scenario.steps.map(({ do: step }) => ({
    shown: shownLevel(step.judge.links),
    non_vacuous: nonVacuous(step.judge.defects),
  }));
}

module.exports = { SCALE, shownLevel, nonVacuous, runScenario };
