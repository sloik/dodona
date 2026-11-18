'use strict';
// Trying a judgement again (decision 0024, conformance/README.md, attempts scenarios).
// Each attempt is { ticket, target, state } where `state` is `open`, `agreed`
// or `refused` and `target` counts the changes of target before it was taken.

const { rank } = require('./intent');
const vocabulary = require('./vocabulary');

class InvalidScenario extends Error {}

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

// The claimed level, lowered to helper if the cap applies and the claim was higher.
function grantedLevel(claims, capped) {
  if (capped && rank(claims) > rank('helper')) return 'helper';
  return claims;
}

// How many attempts along the line did not agree: refused, or still open.
function notAgreed(attempts) {
  return attempts.filter((attempt) => attempt.state !== 'agreed').length;
}

// The limit on refusals along the line before every retried agreement is capped
// (decision 0031): a whole number of at least one, 2 when absent. Any other value
// makes the scenario invalid, and it is refused as a whole (conformance/README.md).
function refusalLimit(scenario) {
  const limit = scenario.refusals_before_cap;
  if (limit === undefined) return 2;
  if (!Number.isInteger(limit) || limit < 1) throw new InvalidScenario('refusals_before_cap must be a whole number of at least one');
  return limit;
}

// Checked before any step is taken, so that the refusal is not mistaken for a step that threw.
function validate(scenario) {
  refusalLimit(scenario);
}

// `all` is every attempt ever taken; the current target's are those with `target` equal to `current`.
// Every field is worked out from the attempts as they stand now.
function judge(all, current, claims, limit = 2) {
  const onTarget = all.filter((attempt) => attempt.target === current);
  const shopped = isShopped(onTarget);
  const retried = isShopped(all);
  const capped = shopped || (retried && notAgreed(all) >= limit);
  const answer = {
    result: overallResult(onTarget),
    shopped,
    cap: capped ? 'helper' : null,
    attempts: all.length,
    retried,
  };
  if (claims !== undefined) answer.granted = grantedLevel(claims, capped);
  return answer;
}

function runScenario(scenario) {
  const all = [];
  const limit = refusalLimit(scenario);
  let current = 0;
  const results = [];
  for (const { do: step } of scenario.steps) {
    if (step.take && vocabulary.isString(step.take.as)) {
      all.push({ ticket: step.take.as, target: current, state: 'open' });
    } else if (step.close && vocabulary.isString(step.close.ticket) && vocabulary.RESULTS.includes(step.close.result)) {
      const attempt = all.find((candidate) => candidate.ticket === step.close.ticket && candidate.state === 'open');
      if (attempt) attempt.state = step.close.result;
    } else if (step.change_target) {
      current += 1;
    }
    results.push(judge(all, current, scenario.claims, limit));
  }
  return results;
}

module.exports = { InvalidScenario, validate, overallResult, isShopped, notAgreed, refusalLimit, grantedLevel, judge, runScenario };
