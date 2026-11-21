'use strict';
// PROTOTYPE, unwired: mock conformance scenarios for prototype-supervised-executor.js.
// No process is started, no signal is sent, no process table is read: the supervisor,
// its private channel, the executor's streams and the clock are all stand-ins.
// Run alone: node --test kernel2/test-prototype-supervised-executor.js

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { PassThrough, Writable } = require('node:stream');
const { superviseBatch } = require('./prototype-supervised-executor');

// A clock whose waits fire only when the test says so.
function fakeClock() {
  const waits = [];
  return {
    waits,
    wait(ms) {
      let fire;
      const promise = new Promise((resolve) => { fire = resolve; });
      const entry = { ms, fire, promise, cancelled: false };
      waits.push(entry);
      return { promise, cancel() { entry.cancelled = true; } };
    },
    fire(index) { waits[index].fire(); },
  };
}

// A stand-in supervisor reached over a private channel. It never exposes a numeric id.
// `script(sup)` plays it once launched.
function fakeSupervisor(script, { stall = false } = {}) {
  const launched = [];
  const launch = (argv, cwd) => {
    const sup = { argv, cwd, received: [], cleanupRequests: 0, events: [] };
    sup.stdout = new PassThrough();
    sup.stdin = new Writable({
      write(chunk, encoding, callback) {
        sup.received.push(chunk);
        if (!stall) callback(null);
      },
    });
    sup.stdin.on('error', () => {});
    sup.ownership = new Promise((resolve) => { sup.own = resolve; });
    sup.exited = new Promise((resolve) => { sup.exit = resolve; });
    sup.lost = new Promise((resolve) => { sup.lose = () => { sup.events.push('lost'); resolve(); }; });
    sup.cleanupReply = null;
    sup.requestCleanup = () => {
      sup.cleanupRequests += 1;
      sup.events.push('cleanup-requested');
      if (sup.loseOnCleanup) sup.lose();
      return new Promise((resolve) => { sup.cleanupReply = resolve; if (sup.autoAck) resolve('acknowledged'); });
    };
    launched.push(sup);
    setImmediate(() => script(sup));
    return sup;
  };
  return { launch, launched };
}

const LINE = '{"ended":true,"reports":[]}\n';
const happy = (sup) => {
  sup.autoAck = true;
  sup.own('confirmed');
  sup.stdout.write(LINE);
  sup.stdout.end();
  sup.exit(0);
};

function run(fake, clock, options = {}) {
  return superviseBatch(['run-batch'], 'the-root', { runs: [] }, 1000, {
    platform: 'linux', launch: fake.launch, clock, cleanupWaitMs: 500, ...options,
  });
}

// --- Planted control first: losing the supervisor before cleanup. ---

// Loads a copy of the prototype with `needle` replaced, as test-run.js's planted() does.
function planted(needle, replacement) {
  const source = fs.readFileSync(path.join(__dirname, 'prototype-supervised-executor.js'), 'utf8');
  assert.ok(source.includes(needle), `the planted defect must change something: ${needle}`);
  const where = fs.mkdtempSync(path.join(os.tmpdir(), 'planted-supervisor-'));
  const damaged = source.replace(needle, replacement)
    .replace(/require\('\.\/([^']+)'\)/g, (whole, name) => `require(${JSON.stringify(path.join(__dirname, name))})`);
  fs.writeFileSync(path.join(where, 'prototype-supervised-executor.js'), damaged);
  return require(path.join(where, 'prototype-supervised-executor.js'));
}

// A whole, valid exchange; then the anchor is gone before the cleanup request is answered.
const loseBeforeCleanup = (sup) => {
  sup.loseOnCleanup = true;
  sup.own('confirmed');
  sup.stdout.write(LINE);
  sup.stdout.end();
  sup.exit(0);
};

test('supervisor lost before cleanup: the answer is withheld', async () => {
  const fake = fakeSupervisor(loseBeforeCleanup);
  const got = await run(fake, fakeClock());
  assert.deepEqual(got, { withheld: 'supervisor-lost' });
});

test('planted: a supervisor lost before cleanup still counted', async () => {
  const damaged = planted('if (!held) return', 'if (false) return');
  const fake = fakeSupervisor(loseBeforeCleanup);
  const got = await damaged.superviseBatch(['run-batch'], 'the-root', { runs: [] }, 1000, {
    platform: 'linux', launch: fake.launch, clock: fakeClock(), cleanupWaitMs: 500,
  });
  assert.deepEqual(got, { answer: { ended: true, reports: [] }, cleanup: 'requested' },
    'the check can fail: the damaged copy lets the answer through');
});

// --- Positive simulated phases. ---

test('confirmed ownership, input written whole, exit 0, real EOF, first LF line: answer, cleanup only requested', async () => {
  const fake = fakeSupervisor(happy);
  const got = await run(fake, fakeClock());
  assert.deepEqual(got, { answer: { ended: true, reports: [] }, cleanup: 'requested' });
  const sup = fake.launched[0];
  assert.equal(Buffer.concat(sup.received).toString('utf8'), `${JSON.stringify({ runs: [] })}\n`);
  assert.equal(sup.cleanupRequests, 1);
  assert.notEqual(got.cleanup, 'complete', 'an acknowledged request is never proof every descendant ended');
});

test('a first line of any length, later lines dropped', async () => {
  const pad = 'x'.repeat(17 * 1048576);
  const fake = fakeSupervisor((sup) => {
    sup.autoAck = true;
    sup.own('confirmed');
    const line = `{"ended":true,"reports":[],"pad":"${pad}"}\n`;
    for (let at = 0; at < line.length; at += 1048576) sup.stdout.write(line.slice(at, at + 1048576));
    sup.stdout.write('{"later":1.5}\n');
    sup.stdout.end();
    sup.exit(0);
  });
  const got = await run(fake, fakeClock(), {});
  assert.equal(got.answer && got.answer.pad.length, pad.length);
});

// --- Withholding: loss, noncompletion, unconfirmed ownership. ---

test('ownership refused or never confirmed: nothing written, answer withheld, cleanup still requested', async () => {
  const refused = fakeSupervisor((sup) => { sup.autoAck = true; sup.own('refused'); });
  assert.deepEqual(await run(refused, fakeClock()), { withheld: 'ownership-unconfirmed' });
  assert.equal(refused.launched[0].received.length, 0, 'no input before ownership is confirmed');
  assert.equal(refused.launched[0].cleanupRequests, 1);

  const clock = fakeClock();
  const silent = fakeSupervisor((sup) => { sup.autoAck = true; setImmediate(() => clock.fire(0)); });
  assert.deepEqual(await run(silent, clock), { withheld: 'ownership-unconfirmed' }, 'never confirmed by the deadline');
  assert.equal(silent.launched[0].received.length, 0);
});

test('noncompletion: no exit, no EOF or unread input is a timeout at the one deadline', async () => {
  for (const [script, options, why] of [
    [(sup) => { sup.autoAck = true; sup.own('confirmed'); sup.stdout.write(LINE); sup.exit(0); }, {}, 'output held open'],
    [(sup) => { sup.autoAck = true; sup.own('confirmed'); sup.stdout.write(LINE); sup.stdout.end(); }, {}, 'no exit'],
    [happy, { stall: true }, 'input never read'],
  ]) {
    const clock = fakeClock();
    const fake = fakeSupervisor((sup) => { script(sup); setImmediate(() => setImmediate(() => clock.fire(0))); }, options);
    assert.deepEqual(await run(fake, clock), { timedOut: true, cleanup: 'requested' }, why);
    assert.equal(clock.waits[0].ms, 1000, why);
  }
});

test('supervisor lost mid-run, or cleanup unanswered within its bound: withheld', async () => {
  const mid = fakeSupervisor((sup) => { sup.autoAck = true; sup.own('confirmed'); sup.lose(); });
  assert.deepEqual(await run(mid, fakeClock()), { withheld: 'supervisor-lost' });

  const clock = fakeClock();
  const mute = fakeSupervisor((sup) => {
    sup.own('confirmed'); sup.stdout.write(LINE); sup.stdout.end(); sup.exit(0);
    const poll = () => (sup.cleanupRequests ? clock.fire(clock.waits.length - 1) : setImmediate(poll));
    setImmediate(poll);
  });
  assert.deepEqual(await run(mute, clock), { withheld: 'cleanup-unconfirmed' });
});

test('supervisor exit after acknowledgement is not treated as proof', async () => {
  const fake = fakeSupervisor((sup) => { happy(sup); sup.lose(); });
  const got = await run(fake, fakeClock());
  // Lost at any point before cleanup is acknowledged: withheld, never "all ended".
  assert.ok(got.withheld === 'supervisor-lost' || got.cleanup === 'requested');
  assert.notEqual(got.cleanup, 'complete');
});

// --- Platform and the forbidden fallbacks. ---

test('Windows and unlisted platforms are unavailable before anything is launched', async () => {
  for (const platform of ['win32', 'aix', 'sunos', 'haiku', undefined]) {
    const fake = fakeSupervisor(happy);
    assert.deepEqual(await run(fake, fakeClock(), { platform }), { unavailable: 'platform' }, String(platform));
    assert.equal(fake.launched.length, 0, String(platform));
  }
});

test('the prototype holds no numeric id, sends no signal and has no endTree fallback', () => {
  const source = fs.readFileSync(path.join(__dirname, 'prototype-supervised-executor.js'), 'utf8')
    .replace(/^\s*\/\/.*$/gm, '');
  for (const forbidden of ['process.kill', '.pid', 'endTree', 'killGroup', 'require(\'./processes\')', 'child_process']) {
    assert.ok(!source.includes(forbidden), forbidden);
  }
});
