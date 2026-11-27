'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { retryAndLateReply } = require('./fixture.cjs');

test('retry and late reply debit at most once', () => {
  const result = retryAndLateReply();
  assert.equal(result.checkout.attempts, 2);
  assert.deepEqual(result.checkout.delivered, [2, 1]);
  assert.ok(result.debits <= 1, `received ${result.debits} debits`);
});
