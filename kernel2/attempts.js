'use strict';
// Trying a judgement again (decision 0024, conformance/README.md, attempts scenarios).
// `attempts` are the ones taken on the current target, in order; each has a
// `state` of `open`, `agreed` or `refused`.

// `none`, `agreed` or `refused`. An open attempt counts as a failure.
function overallResult(attempts) {
  if (attempts.length === 0) return 'none';
  return attempts.every((attempt) => attempt.state === 'agreed') ? 'agreed' : 'refused';
}

// True if some attempt closed as agreed was taken after one that is not agreed.
function isShopped(attempts) {
  return attempts.some((attempt, position) => attempt.state === 'agreed'
    && attempts.slice(0, position).some((earlier) => earlier.state !== 'agreed'));
}

function judge(attempts, taken) {
  const shopped = isShopped(attempts);
  return { result: overallResult(attempts), shopped, cap: shopped ? 'helper' : null, attempts: taken };
}

function runScenario(scenario) {
  let attempts = [];
  let taken = 0;
  const results = [];
  for (const { do: step } of scenario.steps) {
    if (step.take) {
      attempts.push({ ticket: step.take.as, state: 'open' });
      taken += 1;
    } else if (step.close) {
      const attempt = attempts.find((candidate) => candidate.ticket === step.close.ticket);
      if (attempt) attempt.state = step.close.result;
    } else if (step.change_target) {
      attempts = [];
    }
    results.push(judge(attempts, taken));
  }
  return results;
}

module.exports = { overallResult, isShopped, judge, runScenario };
