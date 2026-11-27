'use strict';
// The whole-project report (conformance/README.md, status scenarios).

const { identityOf, coreKey } = require('./identity');
const vocabulary = require('./vocabulary');
const { SCALE } = require('./assurance');
const { gradeAct } = require('./acts');
const { LEVELS, rank } = require('./intent');

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

// A gate nobody can read is hard: a mistake in writing a gate can only make delivery harder.
function effectiveGate(gate) {
  return vocabulary.GATES.includes(gate) ? gate : 'hard';
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
    && RECORD_FIELDS.every((field) => (field === 'preimage' ? isObject(body[field]) : typeof body[field] === 'string'));
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
function countingRecords(name, preimage, records, state) {
  const current = identityOf(preimage);
  const writers = [state.self.writer, ...state.policy.trusted_writers];
  return records
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

  // Checks of this intent's criteria. Descendant totals are folded separately.
  const all = Object.values(intent.criteria).map((criterion) => {
    const states = criterion.checked_by.map((obligation) => statusOf(obligations, obligation));
    // A criterion is met only if something checks it and every obligation passed.
    const met = states.length > 0 && states.every((state) => state === 'passed');
    return { gate: effectiveGate(criterion.gate), met, states };
  });
  const uncovered = all.some((criterion) => criterion.states.length === 0);

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
  const open = !confirmed || all.some((c) => c.gate === 'hard' && !c.met);
  const failed = all.some((c) => c.gate === 'hard' && c.states.some((s) => s === 'failed' || s === 'conflict'));
  return { baseline, gates, score, shown, exceptions, separation, confirmed, uncovered, open, failed, unguarded: false, complete: false };
}

// The highest of some levels; `self` if there are none.
function highest(levels) {
  return levels.reduce((a, b) => (rank(b) > rank(a) ? b : a), LEVELS[0]);
}

// The status of an obligation; one the scenario does not define is unknown.
function statusOf(obligations, name) {
  return Object.hasOwn(obligations, name) ? obligations[name].status : 'unknown';
}

// The defined intents in postorder, from leaves towards their roots.
function treeOrder(intents) {
  const parents = new Map();
  const remaining = new Map(Object.keys(intents).map((name) => [name, 0]));
  for (const name of [...remaining.keys()].sort()) {
    for (const child of intents[name].children) {
      if (!remaining.has(child) || parents.has(child)) continue;
      parents.set(child, name);
      remaining.set(name, remaining.get(name) + 1);
    }
  }
  const order = [...remaining.keys()].filter((name) => remaining.get(name) === 0);
  for (const name of order) {
    if (!parents.has(name)) continue;
    const parent = parents.get(name);
    const left = remaining.get(parent) - 1;
    remaining.set(parent, left);
    if (left === 0) order.push(parent);
  }
  return { parents, order };
}

function includeChild(parent, child) {
  for (const count of ['hard', 'soft', 'deferred', 'deferred_open']) parent.gates[count] += child.gates[count];
  parent.score.met += child.score.met;
  parent.score.of += child.score.of;
  for (const flag of ['uncovered', 'open', 'unguarded', 'failed']) parent[flag] ||= child[flag];
}

function treeStatus(intent, minimum) {
  if (!intent.confirmed) return 'draft';
  if (intent.uncovered) return 'uncovered';
  if (intent.unguarded || intent.gates.hard < minimum) return 'unguarded';
  if (!intent.complete || intent.open) return 'open';
  return intent.gates.deferred_open > 0 ? 'delivered' : 'fulfilled';
}

// The project status from the intent reports over their respective subtrees.
function projectStatus(policy, reports) {
  if (policy.required.length === 0) return 'nothing-required';
  const failing = policy.required.some((id) => Object.hasOwn(reports, id) && reports[id].failed);
  if (failing) return 'failed';
  // A required intent the scenario does not define counts as not delivered.
  if (policy.required.every((id) => Object.hasOwn(reports, id) && ['delivered', 'fulfilled'].includes(reports[id].status))) return 'passed';
  return 'unknown';
}

// Sets a key as an own data property, so an obligation named `__proto__` is kept as data.
function put(object, key, value) {
  Object.defineProperty(object, key, { value, enumerable: true, writable: true, configurable: true });
}

function report(state, ledger) {
  const checked = ledger.filter(isRecord).map(({ body }) => ({ body, rejected: isRejected(body) }));
  const usable = checked.filter(({ rejected }) => !rejected).map(({ body }) => body);
  const obligations = {};
  const levels = {};
  for (const [name, details] of Object.entries(state.obligations)) {
    const records = countingRecords(name, details.preimage, usable, state);
    const judged = obligationStatus(records);
    put(obligations, name, judged);
    put(levels, name, obligationLevel(judged.status, records));
  }
  const reports = {};
  const { parents, order } = treeOrder(state.intents);
  for (const [id, intent] of Object.entries(state.intents)) {
    put(reports, id, judgeIntent(id, intent, obligations, levels, ledger, state));
  }
  for (const id of order) {
    const judged = reports[id];
    judged.complete = true;
    judged.unguarded ||= judged.gates.hard === 0;
    if (parents.has(id)) includeChild(reports[parents.get(id)], judged);
  }
  const shown = {};
  for (const [id, judged] of Object.entries(reports)) {
    const minimum = parents.has(id) ? 1 : Math.max(1, state.policy.min_hard_gates);
    judged.status = treeStatus(judged, minimum);
    put(shown, id, {
      status: judged.status, baseline: judged.baseline, gates: judged.gates, score: judged.score, shown: judged.shown, exceptions: judged.exceptions, separation: judged.separation,
    });
  }
  const rejected = checked.filter((record) => record.rejected).length;
  return {
    obligations,
    intents: shown,
    project: { status: projectStatus(state.policy, reports) },
    rejected,
  };
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
    if (step.append && typeof step.append.kind === 'string' && isObject(step.append.body)) ledger.push({ kind: step.append.kind, body: step.append.body });
    else if (step.change && typeof step.change.obligation === 'string' && Object.hasOwn(state.obligations, step.change.obligation) && isObject(step.change.preimage)) state.obligations[step.change.obligation].preimage = step.change.preimage;
    else if (step.set_gate && typeof step.set_gate.intent === 'string' && typeof step.set_gate.criterion === 'string' && vocabulary.GATES.includes(step.set_gate.to) && Object.hasOwn(state.intents, step.set_gate.intent) && Object.hasOwn(state.intents[step.set_gate.intent].criteria, step.set_gate.criterion)) state.intents[step.set_gate.intent].criteria[step.set_gate.criterion].gate = step.set_gate.to;
    return report(state, ledger);
  });
}

module.exports = { baselineOf, pairingTarget, levelFor, report, runScenario };
