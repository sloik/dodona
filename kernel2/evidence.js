'use strict';
// Obligation status (MODEL.md section 4), shared by the `scenario` and `states` commands.
//
// A ledger entry (a record, a running check or an outcome) is filed under the
// inputs it was given: the content of the definitions its obligation depends on,
// and the tool. It counts for an obligation only when those match the current ones.

const vocabulary = require('./vocabulary');

const { isString } = vocabulary;

function inputsOf(definitions, dependsOn) {
  const inputs = {};
  for (const definition of dependsOn) inputs[definition] = definitions[definition];
  return inputs;
}

function sameInputs(a, b) {
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  return keysA.length === keysB.length && keysA.every((key) => key in b && a[key] === b[key]);
}

// True if `entry` was filed under the current inputs of this obligation.
function counts(entry, obligation, dependsOn, current) {
  return entry.obligation === obligation
    && entry.tool === current.tool
    && sameInputs(entry.inputs, inputsOf(current.definitions, dependsOn));
}

// Judges one obligation. `ledger` holds `records` (with a verdict), `running`
// and `outcomes` (with an outcome of `unavailable` or `error`).
// Returns { status, pending, reason }; reason is null unless the status is unknown.
function judgeObligation(obligation, dependsOn, current, ledger) {
  const here = (entry) => counts(entry, obligation, dependsOn, current);
  const verdicts = ledger.records.filter(here).map((record) => record.verdict);
  if (verdicts.length > 0) {
    const anyPassed = verdicts.includes('passed');
    const anyFailed = verdicts.includes('failed');
    if (anyPassed && anyFailed) return { status: 'conflict', pending: false, reason: null };
    if (anyPassed) return { status: 'passed', pending: false, reason: null };
    return { status: 'failed', pending: false, reason: null };
  }
  if (ledger.running.some(here)) return { status: 'unknown', pending: true, reason: 'pending' };
  const outcomes = ledger.outcomes.filter(here);
  if (outcomes.length > 0) return { status: 'unknown', pending: false, reason: outcomes[outcomes.length - 1].outcome };
  return { status: 'unknown', pending: false, reason: 'never-run' };
}

// Runs an evidence scenario. Returns the list of results, one per step.
function runScenario(scenario) {
  const state = {
    definitions: { ...scenario.start.definitions },
    tool: scenario.start.tool,
    backend: scenario.start.backend,
  };
  const ledger = { records: [], running: [], outcomes: [] };
  const dependsOn = (obligation) => (Object.hasOwn(scenario.obligations, obligation) ? scenario.obligations[obligation] : {}).depends_on;
  const results = [];

  for (const { do: step } of scenario.steps) {
    if (step.edit && isString(step.edit.definition) && isString(step.edit.to) && Object.hasOwn(state.definitions, step.edit.definition)) {
      state.definitions[step.edit.definition] = step.edit.to;
    } else if (step.repin && isString(step.repin.to)) {
      state.tool = step.repin.to;
    } else if (step.backend && vocabulary.BACKENDS.includes(step.backend.to)) {
      state.backend = step.backend.to;
    } else if (step.submit && isString(step.submit.obligation) && isString(step.submit.as) && dependsOn(step.submit.obligation) !== undefined
        && !ledger.running.some((run) => run.run === step.submit.as)) {
      // A submit under a name that is in flight, or for an unknown obligation, changes nothing.
      const obligation = step.submit.obligation;
      const entry = { obligation, inputs: inputsOf(state.definitions, dependsOn(obligation)), tool: state.tool };
      if (state.backend === 'up') {
        ledger.running.push({ ...entry, run: step.submit.as });
      } else {
        ledger.outcomes.push({ ...entry, outcome: 'unavailable' });
      }
    } else if (step.complete && isString(step.complete.run) && vocabulary.VERDICTS.includes(step.complete.verdict)) {
      const at = ledger.running.findIndex((run) => run.run === step.complete.run);
      if (at >= 0) {
        const [run] = ledger.running.splice(at, 1);
        ledger.records.push({ obligation: run.obligation, inputs: run.inputs, tool: run.tool, verdict: step.complete.verdict });
      }
    } else if (step.lose && isString(step.lose.run)) {
      const at = ledger.running.findIndex((run) => run.run === step.lose.run);
      if (at >= 0) {
        const [run] = ledger.running.splice(at, 1);
        ledger.outcomes.push({ obligation: run.obligation, inputs: run.inputs, tool: run.tool, outcome: 'error' });
      }
    }
    const result = {};
    for (const obligation of Object.keys(scenario.obligations)) {
      const judged = judgeObligation(obligation, dependsOn(obligation), state, ledger);
      result[obligation] = judged.status === 'unknown' ? { status: 'unknown', reason: judged.reason } : { status: judged.status };
    }
    results.push(result);
  }
  return results;
}

// The `states` command for kind "evidence": each state is judged on its own.
function judgeStates(request) {
  return request.states.map((state) => {
    const current = { definitions: state.definitions, tool: state.tool };
    const ledger = { records: state.records, running: state.running, outcomes: [] };
    const result = {};
    for (const [obligation, details] of Object.entries(request.obligations)) {
      const judged = judgeObligation(obligation, Array.isArray(details) ? details : details.depends_on, current, ledger);
      result[obligation] = { status: judged.status, pending: judged.pending };
    }
    return result;
  });
}

module.exports = { inputsOf, sameInputs, counts, judgeObligation, runScenario, judgeStates };
