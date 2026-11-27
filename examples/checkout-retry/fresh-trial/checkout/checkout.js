'use strict';

function runCheckout(events, {
  idempotent = true,
  chargingAvailable = true,
  settlementAvailable = true,
} = {}) {
  const captures = new Map();
  const attempts = new Map();
  let timedOut = false;
  let status = 'pending';

  function handle({ action, attempt }) {
    switch (action) {
      case 'submit': {
        if (attempts.has(attempt) || (attempt === 2 && !timedOut)) {
          throw new Error('Invalid fake checkout submission');
        }
        attempts.set(attempt, { state: 'submitted', charge: null });
        break;
      }
      case 'process': {
        const request = attempts.get(attempt);
        if (request?.state !== 'submitted') {
          throw new Error('The fake gateway can process each submission once');
        }
        const key = idempotent ? 'synthetic-order' : 'synthetic-order-' + attempt;
        if (chargingAvailable && !captures.has(key)) {
          captures.set(key, 'fake-charge-' + (captures.size + 1));
        }
        request.charge = captures.get(key) ?? null;
        request.state = 'processed';
        break;
      }
      case 'timeout': {
        if (attempt !== 1 || attempts.get(1)?.state !== 'processed' || timedOut) {
          throw new Error('Only the first processed attempt can time out once');
        }
        timedOut = true;
        break;
      }
      case 'reply': {
        const request = attempts.get(attempt);
        if (request?.state !== 'processed') {
          throw new Error('Only a processed attempt may reply once');
        }
        request.state = 'replied';
        if (request.charge && settlementAvailable) {
          status = 'settled';
        }
        break;
      }
      default:
        throw new Error('Unknown fake checkout event');
    }

    return {
      action,
      attempt,
      late: action === 'reply' && attempt === 1 && timedOut,
      attemptCharge: attempts.get(attempt)?.charge ?? null,
      charges: Array.from(captures.values()),
      status,
    };
  }

  return events.map(handle);
}

module.exports = { runCheckout };
