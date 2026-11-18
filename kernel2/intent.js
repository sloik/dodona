'use strict';
// Intent status and exceptions (MODEL.md section 5, decision 0024), shared by
// the `scenario` and `states` commands.

const vocabulary = require('./vocabulary');

const LEVELS = ['self', 'helper', 'apart', 'tested', 'cross-make', 'credentialed'];

// The highest level each source of facts can earn.
const SOURCE_CAP = { declared: 'helper', attested: 'cross-make' };

function rank(level) {
  const position = LEVELS.indexOf(level);
  return position < 0 ? 0 : position; // a level we do not know counts as the lowest
}

function lower(a, b) {
  return rank(a) <= rank(b) ? a : b;
}

// The separation the kernel grants an exception.
// `amendment` is { by, claims?, source? }.
function grantedLevel(amendment) {
  if (amendment.by === 'worker') return 'self';
  if (amendment.claims === undefined || amendment.claims === null) return 'self';
  const source = amendment.source === 'attested' ? 'attested' : 'declared';
  return lower(amendment.claims, SOURCE_CAP[source]);
}

// Judges one requested exception. Returns { takes_effect, level }.
function judgeAmendment(policy, amendment) {
  const level = grantedLevel(amendment);
  const takesEffect = amendment.by === 'owner' && rank(level) >= rank(policy.exception_separation);
  return { takes_effect: takesEffect, level };
}

// Intent status. `criteria` maps a criterion to { gate, check }.
function intentStatus(policy, confirmed, criteria) {
  const minimum = Math.max(1, policy.min_hard_gates); // a floor below 1 is 1
  const all = Object.values(criteria);
  const hard = all.filter((criterion) => criterion.gate === 'hard');
  const deferred = all.filter((criterion) => criterion.gate === 'deferred');
  if (!confirmed) return 'draft';
  if (hard.length < minimum) return 'unguarded';
  if (hard.some((criterion) => criterion.check !== 'passed')) return 'open';
  if (deferred.every((criterion) => criterion.check === 'passed')) return 'fulfilled';
  return 'delivered';
}

// True if an amend step names a criterion that exists and carries only allowed values.
function validAmend(step, known) {
  const claimsOk = step.claims === undefined || step.claims === null || LEVELS.includes(step.claims);
  const sourceOk = step.source === undefined || vocabulary.SOURCES.includes(step.source);
  return known(step.criterion) && vocabulary.GATES.includes(step.to) && ['owner', 'worker'].includes(step.by) && claimsOk && sourceOk;
}

// Runs an intent scenario. Returns the list of results, one per step.
function runScenario(scenario) {
  const criteria = {};
  for (const [name, details] of Object.entries(scenario.criteria)) criteria[name] = { gate: details.gate, check: 'unknown' };
  let confirmed = false;
  const results = [];

  for (const { do: step } of scenario.steps) {
    let amendment = null;
    const known = (name) => Object.hasOwn(criteria, name);
    if (step.confirm) {
      confirmed = true;
    } else if (step.check && known(step.check.criterion) && vocabulary.CHECKS.includes(step.check.status)) {
      criteria[step.check.criterion].check = step.check.status;
    } else if (step.edit && known(step.edit.criterion) && vocabulary.GATES.includes(step.edit.to)) {
      if (criteria[step.edit.criterion].gate !== step.edit.to) {
        criteria[step.edit.criterion].gate = step.edit.to;
        confirmed = false;
      }
    } else if (step.amend && validAmend(step.amend, known)) {
      const judged = judgeAmendment(scenario.policy, step.amend);
      if (judged.takes_effect) criteria[step.amend.criterion].gate = step.amend.to;
      amendment = { takes_effect: judged.takes_effect, level: judged.level };
    }
    const result = { status: intentStatus(scenario.policy, confirmed, criteria) };
    if (amendment !== null) result.amendment = amendment;
    results.push(result);
  }
  return results;
}

// The `states` command for kind "intent": each state is judged on its own.
function judgeStates(request) {
  return request.states.map((state) => ({
    status: intentStatus(request.policy, state.confirmed, state.criteria),
    amendments: state.amendments.map((amendment) => judgeAmendment(request.policy, amendment)),
  }));
}

module.exports = { LEVELS, rank, grantedLevel, judgeAmendment, intentStatus, runScenario, judgeStates };
