'use strict';
// The `states` command: judge single states. Uses the same rule functions as scenarios.

const evidence = require('./evidence');
const intent = require('./intent');

// Returns { results: [...] }, one per state, or throws if the kind is not known.
function judgeStates(request) {
  if (request.kind === 'evidence') return { results: evidence.judgeStates(request) };
  if (request.kind === 'intent') return { results: intent.judgeStates(request) };
  throw new Error(`unknown states kind: ${request.kind}`);
}

module.exports = { judgeStates };
