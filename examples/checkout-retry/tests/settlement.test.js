'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { retryAndLateReply } = require('./fixture.cjs');

test('a paid retry settles and a late reply leaves it settled', () => {
  const result = retryAndLateReply();
  assert.ok(result.debits > 0, "a debit must occur before settlement");
  assert.equal(result.afterRetry, 'settled');
  assert.equal(result.checkout.status, 'settled');
});
