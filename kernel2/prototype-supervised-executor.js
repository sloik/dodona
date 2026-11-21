'use strict';
// PROTOTYPE, unwired, defensive. Not reached from dodona-kernel2.js, project-run.js or any
// command; only the test-prototype-*.js files require it. It changes no contract
// and serves no decision.
//
// The idea under test: on a supported Unix the parent does not own the executor's process
// group itself. A detached supervisor (prototype-unix-supervisor.js, reached through
// prototype-supervisor-transport.js) leads a new session and group of its own, starts the
// executor undetached inside it, relays its standard streams over a private channel, and
// on request ends its own group while it is alive as the ownership anchor. The parent
// holds no numeric id of any process and never signals anything; it only asks.
//
// What the parent may conclude:
// - An answer counts only if ownership was confirmed before any input was written, the
//   batch was written whole, the executor exited with 0, its output reached a real end,
//   and its first line ended in a line feed, all within the one deadline (as executeBatch
//   in project-run.js); and the supervisor then acknowledged the cleanup request while
//   still alive and within its own bound.
// - An acknowledged cleanup request is never proof that every descendant ended, and nor
//   is the supervisor's exit: the result says `cleanup: 'requested'`, never more.
// - A supervisor lost at any point before acknowledging, ownership never confirmed, or a
//   cleanup unanswered in time: the result is `{ withheld }`. It is NOT `{}`: no check of
//   the batch may be given any verdict from it, `unavailable` included (see
//   verdictsAllowed). Wiring this would refuse the whole run, which step 12 does not yet
//   say: that is a contract change for the owner, proposed and not served.
// - An executor the supervisor could not start, with cleanup then acknowledged: `{}`, as
//   executeBatch gives for a command that cannot start (verdict `unavailable`).
// - Windows and every unlisted platform: `{ unavailable: 'platform' }` before anything is
//   launched. No reviewed job adapter exists in pure Node.
//
// `launch(argv, cwd)` is the private channel to a supervisor: it returns `{ ownership:
// Promise<'confirmed'|other>, stdin, stdout, exited: Promise<exit status>, lost: Promise,
// requestCleanup(): Promise<'acknowledged'|other> }`. `clock.wait(ms)` returns `{ promise,
// cancel() }`. Both are injected; this module starts nothing itself.

const { readReport } = require('./check');

const SUPPORTED = ['linux', 'darwin'];

async function superviseBatch(executor, root, batch, waitMs, { platform, launch, clock, cleanupWaitMs }) {
  if (!SUPPORTED.includes(platform)) return { unavailable: 'platform' };
  const sup = launch(executor, root);
  let lost = false;
  const lostSignal = sup.lost.then(() => {
    lost = true;
    return 'lost';
  });
  const deadline = clock.wait(waitMs);
  const timedOut = deadline.promise.then(() => 'timed-out');
  let result;
  try {
    const owned = await Promise.race([sup.ownership, lostSignal, timedOut]);
    if (owned === 'not-started') {
      result = {};
    } else if (owned !== 'confirmed') {
      result = { withheld: owned === 'lost' ? 'supervisor-lost' : 'ownership-unconfirmed' };
    } else {
      result = await exchange(sup, batch, lostSignal, timedOut);
    }
  } finally {
    deadline.cancel();
  }
  // Always ask, on every way out; never signal, never fall back.
  const bound = clock.wait(cleanupWaitMs);
  const cleanup = await Promise.race([
    Promise.resolve().then(() => sup.requestCleanup()), lostSignal, bound.promise.then(() => 'timed-out'),
  ]);
  bound.cancel();
  // Closing the channel is the last word; a supervisor still alive reads it as a request
  // to end its own group.
  if (typeof sup.release === 'function') sup.release();
  const held = !lost && cleanup === 'acknowledged';
  if (!held) return { withheld: lost ? 'supervisor-lost' : 'cleanup-unconfirmed' };
  if (result.withheld !== undefined) return result;
  return { ...result, cleanup: 'requested' };
}

async function exchange(sup, batch, lostSignal, timedOut) {
  if (sup.stdout.errored || (sup.stdout.destroyed && !sup.stdout.readableEnded)) return {};
  const kept = [];
  let lineDone = false;
  sup.stdout.on('data', (data) => {
    if (lineDone) return;
    const at = data.indexOf(0x0a);
    kept.push(at < 0 ? data : data.subarray(0, at + 1));
    if (at >= 0) lineDone = true;
  });
  const outputEnded = new Promise((resolve) => {
    if (sup.stdout.readableEnded) resolve();
    else sup.stdout.once('end', resolve);
  });
  const outputBroken = new Promise((resolve) => {
    sup.stdout.once('error', () => resolve('not-read'));
    sup.stdout.once('close', () => {
      if (!sup.stdout.readableEnded) resolve('not-read');
    });
  });
  const written = new Promise((resolve) => {
    sup.stdin.once('error', () => resolve(false));
    sup.stdin.end(`${JSON.stringify(batch)}\n`, (error) => resolve(!error));
  });
  let status;
  const exited = sup.exited.then((code) => {
    status = code;
  });
  const done = Promise.all([written, exited, outputEnded]).then(([whole]) => (whole ? 'done' : 'not-written'));
  const how = await Promise.race([done, outputBroken, lostSignal, timedOut]);
  if (how === 'lost') return { withheld: 'supervisor-lost' };
  if (how === 'timed-out') return { timedOut: true };
  if (how !== 'done' || status !== 0 || !lineDone) return {};
  const answer = readReport(Buffer.concat(kept));
  return answer === null ? {} : { answer };
}

// Whether any check of the batch may be given a verdict from this result. A withheld or
// platform-unavailable result gives none, `unavailable` included.
function verdictsAllowed(result) {
  return result !== null && typeof result === 'object'
    && result.withheld === undefined && result.unavailable === undefined;
}

module.exports = { superviseBatch, verdictsAllowed, SUPPORTED };
