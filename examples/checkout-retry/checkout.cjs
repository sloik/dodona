'use strict';

const SETTLE_PAID_RETRY = true;

function startCheckout(order, payments) {
  const delivered = [];
  let attempts = 1;
  let timedOut = false;
  let status = 'pending';

  payments.submit(order, attempts);

  return {
    deadlinePassed() {
      if (attempts !== 1 || timedOut || delivered.includes(1)) {
        throw new Error('the first request is no longer waiting');
      }
      timedOut = true;
    },
    retry() {
      if (attempts !== 1 || !timedOut || status !== 'pending') {
        throw new Error('the order has no retry available');
      }
      attempts = 2;
      payments.submit(order, attempts);
    },
    receive(attempt) {
      const reply = payments.deliver(attempt);
      delivered.push(attempt);
      const firstInTime = attempt === 1 && !timedOut;
      const paidRetryCanSettle = attempt === 2 && SETTLE_PAID_RETRY;
      if (reply.paid && (firstInTime || paidRetryCanSettle)) status = 'settled';
    },
    get status() {
      return status;
    },
    snapshot() {
      return { status, attempts, delivered: [...delivered] };
    },
  };
}

module.exports = { startCheckout };
