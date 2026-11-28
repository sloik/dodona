'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { runCheckout } = require('./checkout');
const schedule = require('./retry-late.json');

test('a successful fake capture leaves the checkout settled', (context) => {
  const trace = runCheckout(schedule);
  context.diagnostic(JSON.stringify(trace));
  const lateReply = trace.at(-1);
  assert.equal(lateReply.late, true);
  assert.equal(lateReply.charges.length, 1);
  assert.equal(lateReply.status, 'settled');
});
