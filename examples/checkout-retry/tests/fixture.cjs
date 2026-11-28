'use strict';

const { startCheckout } = require('../checkout.cjs');

function fakePayments({ deduplicate = true, allowDebit = true } = {}) {
  const debited = new Set();
  const pending = new Map();
  let count = 0;

  return {
    submit(order, attempt) {
      if (pending.has(attempt)) throw new Error('that request is already waiting');
      if (allowDebit && (!deduplicate || !debited.has(order))) {
        debited.add(order);
        count += 1;
      }
      pending.set(attempt, { paid: debited.has(order) });
    },
    deliver(attempt) {
      if (!pending.has(attempt)) throw new Error('no reply for that request');
      const reply = pending.get(attempt);
      pending.delete(attempt);
      return reply;
    },
    get debits() {
      return count;
    },
  };
}

function retryAndLateReply(options) {
  const payments = fakePayments(options);
  const checkout = startCheckout('order', payments);
  checkout.deadlinePassed();
  checkout.retry();
  checkout.receive(2);
  const afterRetry = checkout.status;
  checkout.receive(1);
  return { debits: payments.debits, checkout: checkout.snapshot(), afterRetry };
}

module.exports = { retryAndLateReply };
