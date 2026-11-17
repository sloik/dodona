'use strict';
// The whole-project report (conformance/README.md, status scenarios).

const { identityOf } = require('./identity');
const { gradeAct } = require('./acts');
const { LEVELS, rank, intentStatus } = require('./intent');

const CONFIRM = 'confirm-baseline';
const MATCH = 'match-check';

function sortedCopy(list) {
  return [...list].sort();
}

// The baseline of an intent: the identity of everything that sets its bar.
function baselineOf(intent) {
  const criteria = {};
  for (const [name, criterion] of Object.entries(intent.criteria)) {
    criteria[name] = { gate: criterion.gate, checked_by: sortedCopy(criterion.checked_by) };
  }
  return identityOf({ owner: intent.owner, children: sortedCopy(intent.children), criteria });
}

// The target of an act that says a check tests a criterion.
function pairingTarget(intentId, criterion, obligation) {
  return identityOf({ intent: intentId, criterion, obligation });
}

// The level an act record is graded at for an intent: as in acts scenarios,
// but `self` if its worker is not the intent's worker.
function levelFor(record, intent, policy) {
  if (!record.worker || record.worker.id !== intent.worker) return 'self';
  return gradeAct(record, policy).level;
}

// A record is rejected if its core key is not the identity of its own preimage.
function isRejected(body) {
  return body.core_key !== identityOf(body.preimage);
}

// Status of one obligation from the evidence records that count for it.
function obligationStatus(name, preimage, ledger, state) {
  const current = identityOf(preimage);
  const writers = [state.self.writer, ...state.policy.trusted_writers];
  const verdicts = ledger
    .filter((entry) => entry.kind === 'evidence' && !isRejected(entry.body))
    .map((entry) => entry.body)
    .filter((body) => body.obligation === name
      && writers.includes(body.writer)
      && body.platform === state.self.platform
      && body.core_key === current)
    .map((body) => body.verdict);
  if (verdicts.length === 0) return { status: 'unknown', reason: 'never-run' };
  if (verdicts.every((verdict) => verdict === 'passed')) return { status: 'passed' };
  if (verdicts.every((verdict) => verdict === 'failed')) return { status: 'failed' };
  return { status: 'conflict' };
}

function judgeIntent(id, intent, obligations, ledger, state) {
  const policy = state.policy;
  const baseline = baselineOf(intent);
  const acts = ledger.filter((entry) => entry.kind === 'act' && entry.body.result === 'agreed'
    && entry.body.lineage && entry.body.lineage.intent === id).map((entry) => entry.body);

  // The acts that would confirm the intent but for the floor, at their levels.
  const confirmLevels = acts
    .filter((act) => act.kind === CONFIRM && act.target === baseline && act.actor.id === intent.owner)
    .map((act) => levelFor(act, intent, policy));
  const floor = (policy.floors || {})[CONFIRM] || 'self';
  const confirmed = confirmLevels.some((level) => rank(level) >= rank(floor));

  // Intent status, by the same rule as intent scenarios.
  const criteria = {};
  const hasObligation = {};
  for (const [name, criterion] of Object.entries(intent.criteria)) {
    const states = criterion.checked_by.map((obligation) => obligations[obligation].status);
    hasObligation[name] = criterion.checked_by.length > 0;
    // A criterion is met only if something checks it and every obligation passed.
    const met = states.length > 0 && states.every((state) => state === 'passed');
    criteria[name] = { gate: criterion.gate, check: met ? 'passed' : 'unknown', met, states };
  }
  const uncovered = Object.keys(criteria).some((name) => !hasObligation[name]);
  let status;
  if (!confirmed) status = 'draft';
  else if (uncovered) status = 'uncovered';
  else status = intentStatus(policy, true, criteria);

  const all = Object.values(criteria);
  const gates = {
    hard: all.filter((c) => c.gate === 'hard').length,
    soft: all.filter((c) => c.gate === 'soft').length,
    deferred: all.filter((c) => c.gate === 'deferred').length,
    deferred_open: all.filter((c) => c.gate === 'deferred' && !c.met).length,
  };
  const score = { met: all.filter((c) => c.met).length, of: all.length };

  // Separation: one confirmation, and one match for each criterion and obligation that checks it.
  const matchLevels = [];
  for (const [name, criterion] of Object.entries(intent.criteria)) {
    for (const obligation of criterion.checked_by) {
      const target = pairingTarget(id, name, obligation);
      const levels = acts.filter((act) => act.kind === MATCH && act.target === target).map((act) => levelFor(act, intent, policy));
      matchLevels.push(highest(levels));
    }
  }
  const confirmLevel = highest(confirmLevels);
  const everyLevel = [confirmLevel, ...matchLevels];
  const weakest = everyLevel.reduce((a, b) => (rank(b) < rank(a) ? b : a));
  const separation = {
    weakest,
    act: confirmLevel === weakest ? CONFIRM : MATCH,
    apart_or_better: everyLevel.filter((level) => rank(level) >= rank('apart')).length,
    of: everyLevel.length,
  };
  return { status, gates, score, separation, criteria, uncovered };
}

// The highest of some levels; `self` if there are none.
function highest(levels) {
  return levels.reduce((a, b) => (rank(b) > rank(a) ? b : a), LEVELS[0]);
}

// The project status from the intent reports.
function projectStatus(policy, intents, reports, obligations) {
  if (policy.required.length === 0) return 'nothing-required';
  const failing = policy.required.some((id) => Object.entries(intents[id].criteria).some(([name, criterion]) => (
    criterion.gate === 'hard' && criterion.checked_by.some((o) => ['failed', 'conflict'].includes(obligations[o].status)))));
  if (failing) return 'failed';
  if (policy.required.every((id) => ['delivered', 'fulfilled'].includes(reports[id].status))) return 'passed';
  return 'unknown';
}

function report(state, ledger) {
  const obligations = {};
  for (const [name, details] of Object.entries(state.obligations)) {
    obligations[name] = obligationStatus(name, details.preimage, ledger, state);
  }
  const reports = {};
  const shown = {};
  for (const [id, intent] of Object.entries(state.intents)) {
    const judged = judgeIntent(id, intent, obligations, ledger, state);
    reports[id] = judged;
    shown[id] = { status: judged.status, gates: judged.gates, score: judged.score, separation: judged.separation };
  }
  const rejected = ledger.filter((entry) => entry.kind === 'evidence' && isRejected(entry.body)).length;
  return {
    obligations,
    intents: shown,
    project: { status: projectStatus(state.policy, state.intents, reports, obligations) },
    rejected,
  };
}

function runScenario(scenario) {
  const state = {
    self: scenario.self,
    policy: { trusted_writers: [], required: [], ...scenario.policy },
    obligations: JSON.parse(JSON.stringify(scenario.obligations)),
    intents: JSON.parse(JSON.stringify(scenario.intents)),
  };
  const ledger = [];
  return scenario.steps.map(({ do: step }) => {
    if (step.append && step.append.body && typeof step.append.body === 'object') ledger.push({ kind: step.append.kind, body: step.append.body });
    else if (step.change && state.obligations[step.change.obligation]) state.obligations[step.change.obligation].preimage = step.change.preimage;
    else if (step.set_gate && state.intents[step.set_gate.intent] && state.intents[step.set_gate.intent].criteria[step.set_gate.criterion]) state.intents[step.set_gate.intent].criteria[step.set_gate.criterion].gate = step.set_gate.to;
    return report(state, ledger);
  });
}

module.exports = { baselineOf, pairingTarget, levelFor, report, runScenario };
