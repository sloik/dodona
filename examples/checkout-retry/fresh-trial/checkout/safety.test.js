'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { runCheckout } = require('./checkout');
const schedule = require('./retry-late.json');

test('at most one fake capture through timeout retry and late reply', (context) => {
  const trace = runCheckout(schedule);
  context.diagnostic(JSON.stringify(trace));
  assert.ok(trace.every(({ charges }) => charges.length <= 1));
});
