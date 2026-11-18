'use strict';
// The whole-project report (conformance/README.md, status scenarios).

const { identityOf, coreKey } = require('./identity');
const vocabulary = require('./vocabulary');
const { SCALE } = require('./assurance');
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
    criteria[name] = { words: typeof criterion.words === 'string' ? criterion.words : '', gate: criterion.gate, checked_by: sortedCopy(criterion.checked_by) };
  }
  return identityOf({ owner: intent.owner, words: typeof intent.words === 'string' ? intent.words : '', children: sortedCopy(intent.children), criteria });
}

// The target of an act that says a check tests a criterion.
function pairingTarget(intentId, criterion, obligation) {
  return identityOf({ intent: intentId, criterion, obligation });
}

// The level an act record is graded at for an intent: as in acts scenarios,
// but `self` if its worker is not the intent's worker.
function levelFor(record, intent, policy) {
  try {
    if (!record.worker || record.worker.id !== intent.worker) return 'self';
    return gradeAct(record, policy).level;
  } catch (error) {
    return 'self'; // a record that cannot be understood earns nothing
  }
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

const RECORD_FIELDS = ['obligation', 'platform', 'writer', 'core_key', 'preimage'];

// An evidence entry is a record only if its body is an object with a verdict of
// passed or failed and all the named fields. Anything else is neither counted nor rejected.
function isRecord(entry) {
  const body = entry.body;
  return entry.kind === 'evidence' && isObject(body) && vocabulary.VERDICTS.includes(body.verdict)
    && RECORD_FIELDS.every((field) => body[field] !== undefined);
}

// A record is rejected if its core key is not the identity of its own preimage,
// or its preimage is one that must be refused (an unsorted set, a platform in the key).
function isRejected(body) {
  try {
    return rejectedOrThrow(body);
  } catch (error) {
    return true; // a preimage that cannot be keyed
  }
}

function rejectedOrThrow(body) {
  return body.core_key !== identityOf(body.preimage) || coreKey(JSON.stringify(body.preimage)).refused !== undefined;
}

// The level an evidence record states; `asserted` if it states none or one off the scale.
function statedLevel(body) {
  return SCALE.includes(body.level) ? body.level : 'asserted';
}

// The weakest and the strongest of some levels on the assurance scale.
function weakestOf(levels) {
  return levels.reduce((a, b) => (SCALE.indexOf(b) < SCALE.indexOf(a) ? b : a));
}
function strongestOf(levels) {
  return levels.reduce((a, b) => (SCALE.indexOf(b) > SCALE.indexOf(a) ? b : a));
}

// The evidence records that count for one obligation.
function countingRecords(name, preimage, ledger, state) {
  const current = identityOf(preimage);
  const writers = [state.self.writer, ...state.policy.trusted_writers];
  return ledger
    .filter((entry) => isRecord(entry) && !isRejected(entry.body))
    .map((entry) => entry.body)
    .filter((body) => body.obligation === name
      && writers.includes(body.writer)
      && body.platform === state.self.platform
      && body.core_key === current);
}

// Status of one obligation from the records that count for it.
function obligationStatus(records) {
  const verdicts = records.map((body) => body.verdict);
  if (verdicts.length === 0) return { status: 'unknown', reason: 'never-run' };
  if (verdicts.every((verdict) => verdict === 'passed')) return { status: 'passed' };
  if (verdicts.every((verdict) => verdict === 'failed')) return { status: 'failed' };
  return { status: 'conflict' };
}

// The level an obligation shows: the strongest of its counting records if it passed, otherwise none.
function obligationLevel(status, records) {
  return status === 'passed' ? strongestOf(records.map(statedLevel)) : 'none';
}

function judgeIntent(id, intent, obligations, levels, ledger, state) {
  const policy = state.policy;
  const baseline = baselineOf(intent);
  // Every agreed act record in the ledger; an entry whose body is not an object takes part in no rule.
  const agreed = ledger.filter((entry) => entry.kind === 'act' && isObject(entry.body) && entry.body.result === 'agreed')
    .map((entry) => entry.body);
  // Those that name this intent in their lineage.
  const acts = agreed.filter((act) => isObject(act.lineage) && act.lineage.intent === id);

  // The acts that would confirm the intent but for the floor, at their levels.
  const confirmLevels = acts
    .filter((act) => act.kind === CONFIRM && act.target === baseline && (act.actor || {}).id === intent.owner)
    .map((act) => levelFor(act, intent, policy));
  const floor = (policy.floors || {})[CONFIRM] || 'self';
  const confirmed = confirmLevels.some((level) => rank(level) >= rank(floor));

  // Intent status, by the same rule as intent scenarios.
  const criteria = {};
  const hasObligation = {};
  for (const [name, criterion] of Object.entries(intent.criteria)) {
    const states = criterion.checked_by.map((obligation) => statusOf(obligations, obligation));
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

  // The level shown: the weakest criterion, each the weakest of its obligations.
  const criterionLevels = Object.keys(intent.criteria).sort().map((name) => {
    const own = intent.criteria[name].checked_by.map((obligation) => (Object.hasOwn(levels, obligation) ? levels[obligation] : 'none'));
    return { name, level: own.length === 0 ? 'none' : weakestOf(own) };
  });
  const shownLevel = criterionLevels.length === 0 ? 'none' : weakestOf(criterionLevels.map((item) => item.level));
  const shown = {
    level: shownLevel,
    criterion: (criterionLevels.find((item) => item.level === shownLevel) || { name: null }).name,
  };

  // Exceptions: agreed grants of an amendment, counted if the owner gave them at or above the floor.
  const grantFloor = (policy.floors || {})['grant-amendment'] || 'self';
  const grants = acts.filter((act) => act.kind === 'grant-amendment');
  const counted = grants.filter((act) => (act.actor || {}).id === intent.owner && rank(levelFor(act, intent, policy)) >= rank(grantFloor));
  const exceptions = { counted: counted.length, below_floor: grants.length - counted.length };

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
      const levels = agreed.filter((act) => act.kind === MATCH && act.target === target).map((act) => levelFor(act, intent, policy));
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
  return { status, baseline, gates, score, shown, exceptions, separation, criteria, uncovered };
}

// The highest of some levels; `self` if there are none.
function highest(levels) {
  return levels.reduce((a, b) => (rank(b) > rank(a) ? b : a), LEVELS[0]);
}

// The status of an obligation; one the scenario does not define is unknown.
function statusOf(obligations, name) {
  return Object.hasOwn(obligations, name) ? obligations[name].status : 'unknown';
}

// The project status from the intent reports.
function projectStatus(policy, intents, reports, obligations) {
  if (policy.required.length === 0) return 'nothing-required';
  const defined = policy.required.filter((id) => Object.hasOwn(intents, id));
  const failing = defined.some((id) => Object.values(intents[id].criteria).some((criterion) => (
    criterion.gate === 'hard' && criterion.checked_by.some((o) => ['failed', 'conflict'].includes(statusOf(obligations, o))))));
  if (failing) return 'failed';
  // A required intent the scenario does not define counts as not delivered.
  if (policy.required.every((id) => Object.hasOwn(reports, id) && ['delivered', 'fulfilled'].includes(reports[id].status))) return 'passed';
  return 'unknown';
}

function report(state, ledger) {
  const obligations = {};
  const levels = {};
  for (const [name, details] of Object.entries(state.obligations)) {
    const records = countingRecords(name, details.preimage, ledger, state);
    obligations[name] = obligationStatus(records);
    levels[name] = obligationLevel(obligations[name].status, records);
  }
  const reports = {};
  const shown = {};
  for (const [id, intent] of Object.entries(state.intents)) {
    const judged = judgeIntent(id, intent, obligations, levels, ledger, state);
    reports[id] = judged;
    shown[id] = {
      status: judged.status, baseline: judged.baseline, gates: judged.gates, score: judged.score, shown: judged.shown, exceptions: judged.exceptions, separation: judged.separation,
    };
  }
  const rejected = ledger.filter((entry) => isRecord(entry) && isRejected(entry.body)).length;
  return {
    obligations,
    intents: shown,
    project: { status: projectStatus(state.policy, state.intents, reports, obligations) },
    rejected,
  };
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// Fills in the parts of an intent a scenario may leave out.
function withDefaults(intents) {
  for (const intent of Object.values(intents)) {
    intent.children = intent.children || [];
    intent.criteria = intent.criteria || {};
    for (const criterion of Object.values(intent.criteria)) criterion.checked_by = criterion.checked_by || [];
  }
  return intents;
}

function runScenario(scenario) {
  const state = {
    self: scenario.self,
    policy: { trusted_writers: [], required: [], ...scenario.policy },
    obligations: JSON.parse(JSON.stringify(scenario.obligations || {})),
    intents: withDefaults(JSON.parse(JSON.stringify(scenario.intents || {}))),
  };
  const ledger = [];
  return scenario.steps.map(({ do: step }) => {
    if (step.append && isObject(step.append.body)) ledger.push({ kind: step.append.kind, body: step.append.body });
    else if (step.change && state.obligations[step.change.obligation] && isObject(step.change.preimage)) state.obligations[step.change.obligation].preimage = step.change.preimage;
    else if (step.set_gate && vocabulary.GATES.includes(step.set_gate.to) && state.intents[step.set_gate.intent] && state.intents[step.set_gate.intent].criteria[step.set_gate.criterion]) state.intents[step.set_gate.intent].criteria[step.set_gate.criterion].gate = step.set_gate.to;
    return report(state, ledger);
  });
}

module.exports = { baselineOf, pairingTarget, levelFor, report, runScenario };
