'use strict';
// PROTOTYPE, unwired: mock scenarios and static checks for prototype-unix-supervisor.js and
// prototype-supervisor-transport.js. No process is started and no signal is sent: the
// channel, the supervisor process, the executor, the group probe and the group kill are
// stand-ins. Run alone: node --test kernel2/test-prototype-supervisor-transport.js

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { PassThrough, Writable } = require('node:stream');
const { runSupervisor } = require('./prototype-unix-supervisor');
const { makeLaunch, connect } = require('./prototype-supervisor-transport');
const { superviseBatch, verdictsAllowed } = require('./prototype-supervised-executor');

const tick = () => new Promise((resolve) => setImmediate(resolve));
const settle = async (n = 6) => { for (let i = 0; i < n; i += 1) await tick(); };

function source(name) {
  return fs.readFileSync(path.join(__dirname, name), 'utf8');
}
function code(name) {
  return source(name).replace(/^\s*\/\/.*$/gm, '');
}

// As test-run.js's planted(): a copy of `file` with one change, its own requires resolved here.
function planted(file, needle, replacement) {
  const text = source(file);
  assert.ok(text.includes(needle), `the planted defect must change something: ${needle}`);
  const where = fs.mkdtempSync(path.join(os.tmpdir(), 'planted-supervisor-'));
  const damaged = text.replace(needle, replacement)
    .replace(/require\('\.\/([^']+)'\)/g, (whole, name) => `require(${JSON.stringify(path.join(__dirname, name))})`);
  fs.writeFileSync(path.join(where, file), damaged);
  return require(path.join(where, file));
}

// ---------- The supervisor, with every effect injected. ----------

function supervisorWorld({ leads = true, spawns = true } = {}) {
  const world = { sent: [], kills: 0, exits: [], spawned: [], leads };
  const channel = new EventEmitter();
  channel.connected = true;
  channel.send = (message, callback) => {
    world.sent.push(message);
    setImmediate(() => callback && callback(channel.connected ? null : new Error('closed')));
  };
  world.channel = channel;
  world.deps = {
    channel,
    spawnExecutor: (argv, cwd) => {
      const child = new EventEmitter();
      child.received = [];
      child.stdin = new Writable({ write(chunk, encoding, callback) { child.received.push(chunk); callback(); } });
      child.stdout = new PassThrough();
      child.stdio = [child.stdin, child.stdout, null, { destroyed: false, destroy() { this.destroyed = true; } }];
      world.spawned.push({ argv, cwd, child });
      setImmediate(() => (spawns ? child.emit('spawn') : child.emit('error', new Error('ENOENT'))));
      return child;
    },
    leadsOwnGroup: () => world.leads,
    killOwnGroup: () => { world.kills += 1; },
    exit: (status) => world.exits.push(status),
  };
  world.types = () => world.sent.map((message) => message.type);
  return world;
}

test('supervisor: owned only after leading its group and spawning; input, first line, real end, exit, then its own group ended once', async () => {
  const world = supervisorWorld();
  runSupervisor(world.deps);
  world.channel.emit('message', { type: 'start', argv: ['run-batch', '--x'], cwd: 'the-root' });
  await settle();
  assert.deepEqual(world.spawned.map(({ argv, cwd }) => [argv, cwd]), [[['run-batch', '--x'], 'the-root']]);
  const { child } = world.spawned[0];
  assert.equal(child.stdio[3].destroyed, true, 'descriptor 3 of the executor is a pipe dropped at once, not the channel');
  assert.deepEqual(world.types(), ['owned']);
  world.channel.emit('message', { type: 'input', data: Buffer.from('{"runs":[]}\n') });
  await settle();
  assert.equal(Buffer.concat(child.received).toString(), '{"runs":[]}\n');
  child.stdout.write('{"ended":tr');
  child.stdout.write('ue}\nsecond line\n');
  child.stdout.write('third\n');
  child.stdout.end();
  await settle();
  child.emit('exit', 0, null);
  await settle();
  const relayed = world.sent.filter((m) => m.type === 'stdout').map((m) => m.data.toString()).join('');
  assert.equal(relayed, '{"ended":true}\n', 'up to and including the first line feed, nothing after');
  assert.deepEqual(world.types().filter((t) => t !== 'stdout'), ['owned', 'input-written', 'stdout-end', 'executor-exit']);
  assert.equal(world.kills, 0, 'nothing is ended before it is asked');
  world.channel.emit('message', { type: 'cleanup' });
  assert.equal(world.kills, 0, 'the message is sent before the signal');
  await settle();
  assert.equal(world.types().at(-1), 'cleanup-issuing');
  assert.equal(world.kills, 1);
  world.channel.emit('message', { type: 'cleanup' });
  await settle();
  assert.equal(world.kills, 1, 'once');
});

test('supervisor: not leading a group with its own id: refused, nothing started, nothing signalled', async () => {
  const world = supervisorWorld({ leads: false });
  runSupervisor(world.deps);
  world.channel.emit('message', { type: 'start', argv: ['run-batch'], cwd: 'the-root' });
  await settle();
  assert.deepEqual(world.types(), ['refused']);
  assert.equal(world.spawned.length, 0);
  world.channel.emit('message', { type: 'cleanup' });
  await settle();
  assert.deepEqual(world.types(), ['refused', 'cleanup-impossible']);
  assert.equal(world.kills, 0, 'no group of its own: no signal to anything');
  assert.deepEqual(world.exits, [1]);
});

test('supervisor: an executor that cannot start is not-started', async () => {
  const world = supervisorWorld({ spawns: false });
  runSupervisor(world.deps);
  world.channel.emit('message', { type: 'start', argv: ['nothing-here'], cwd: 'the-root' });
  await settle();
  assert.deepEqual(world.types(), ['not-started']);
});

test('supervisor: the channel lost, or a message out of protocol, ends its own group', async () => {
  const lost = supervisorWorld();
  runSupervisor(lost.deps);
  lost.channel.emit('message', { type: 'start', argv: ['run-batch'], cwd: 'the-root' });
  await settle();
  lost.channel.connected = false;
  lost.channel.emit('disconnect');
  await settle();
  assert.equal(lost.kills, 1, 'the parent gone: the group does not outlive it');

  const stray = supervisorWorld();
  runSupervisor(stray.deps);
  stray.channel.emit('message', { type: 'input', data: Buffer.from('early') });
  await settle();
  assert.deepEqual(stray.types(), ['cleanup-issuing']);
  assert.equal(stray.kills, 1);
});

test('supervisor: an output closed without its end is broken, once', async () => {
  const world = supervisorWorld();
  runSupervisor(world.deps);
  world.channel.emit('message', { type: 'start', argv: ['run-batch'], cwd: 'the-root' });
  await settle();
  world.spawned[0].child.stdout.destroy();
  await settle();
  assert.deepEqual(world.types().filter((t) => t.startsWith('stdout')), ['stdout-broken']);
});

test('planted: the supervisor signals its group without checking it leads one', async () => {
  const damaged = planted('prototype-unix-supervisor.js', 'if (!deps.leadsOwnGroup()) {\n      // Not the leader', 'if (false) {\n      // Not the leader');
  const world = supervisorWorld({ leads: false });
  damaged.runSupervisor(world.deps);
  world.channel.emit('message', { type: 'cleanup' });
  await settle();
  assert.equal(world.kills, 1, 'the check can fail: the damaged copy signals with no group of its own');
});

// ---------- The parent's transport, against a stand-in supervisor process. ----------

// A stand-in for the detached supervisor as the parent sees it. `script[type](sup, message)`
// answers each message the parent sends.
function fakeSupervisorProcess(script) {
  const made = [];
  const spawnSupervisor = () => {
    const sup = new EventEmitter();
    sup.connected = true;
    sup.got = [];
    sup.disconnects = 0;
    sup.unrefs = 0;
    sup.send = (message) => {
      sup.got.push(message);
      const answer = script[message.type];
      if (answer) setImmediate(() => answer(sup, message));
    };
    sup.reply = (message) => sup.emit('message', message);
    sup.die = (status, signal) => {
      sup.connected = false;
      sup.emit('disconnect');
      sup.emit('exit', status, signal);
    };
    sup.disconnect = () => { sup.disconnects += 1; sup.connected = false; setImmediate(() => sup.emit('disconnect')); };
    sup.unref = () => { sup.unrefs += 1; };
    made.push(sup);
    return sup;
  };
  return { spawnSupervisor, made };
}

const LINE = '{"ended":true,"reports":[]}\n';
const owns = (sup) => sup.reply({ type: 'owned' });
const answersBatch = (sup) => {
  sup.reply({ type: 'input-written' });
  sup.reply({ type: 'stdout', data: Buffer.from(LINE) });
  sup.reply({ type: 'stdout-end' });
  sup.reply({ type: 'executor-exit', code: 0, signal: null });
};
const endsGroup = (sup) => {
  sup.reply({ type: 'cleanup-issuing' });
  setImmediate(() => sup.die(null, 'SIGKILL'));
};

function immediateClock() {
  // Deadlines never fire on their own in these cases.
  return { wait() { return { promise: new Promise(() => {}), cancel() {} }; } };
}

function batchThrough(fake, platform = 'linux', mod = { makeLaunch }, clock = immediateClock()) {
  return superviseBatch(['run-batch'], 'the-root', { runs: [] }, 1000, {
    platform, launch: mod.makeLaunch({ platform, spawnSupervisor: fake.spawnSupervisor }), clock, cleanupWaitMs: 500,
  });
}

test('transport: the whole exchange through a stand-in supervisor gives the answer, cleanup only requested', async () => {
  const fake = fakeSupervisorProcess({ start: owns, input: answersBatch, cleanup: endsGroup });
  const got = await batchThrough(fake);
  assert.deepEqual(got, { answer: { ended: true, reports: [] }, cleanup: 'requested' });
  assert.ok(verdictsAllowed(got));
  const sup = fake.made[0];
  assert.deepEqual(sup.got.map((m) => m.type), ['start', 'input', 'cleanup']);
  assert.deepEqual(sup.got[0], { type: 'start', argv: ['run-batch'], cwd: 'the-root' });
  assert.equal(sup.got[1].data.toString(), '{"runs":[]}\n');
  assert.equal(sup.unrefs, 1, 'released');
});

test('transport: owned and broken stdout in the same turn is a failed exchange with cleanup', async () => {
  const fake = fakeSupervisorProcess({
    start: (sup) => {
      owns(sup);
      sup.reply({ type: 'stdout-broken' });
    },
    cleanup: endsGroup,
  });
  assert.deepEqual(await batchThrough(fake), { cleanup: 'requested' });
  const [sup] = fake.made;
  assert.deepEqual(sup.got.map((m) => m.type), ['start', 'cleanup']);
  assert.equal(sup.unrefs, 1);
});

test('transport: broken stdout after a complete first line fails before executor exit', async () => {
  const fake = fakeSupervisorProcess({
    start: owns,
    input: (sup) => {
      sup.reply({ type: 'input-written' });
      sup.reply({ type: 'stdout', data: Buffer.from(LINE) });
      sup.reply({ type: 'stdout-broken' });
    },
    cleanup: endsGroup,
  });
  let expire;
  const clock = { wait(ms) {
    return { promise: new Promise((resolve) => { if (ms === 1000) expire = resolve; }), cancel() {} };
  } };
  const exchange = batchThrough(fake, 'linux', { makeLaunch }, clock);
  await settle();
  expire();
  assert.deepEqual(await exchange, { cleanup: 'requested' });
  const [sup] = fake.made;
  assert.deepEqual(sup.got.map((m) => m.type), ['start', 'input', 'cleanup']);
  assert.equal(sup.unrefs, 1);
});

test('transport: the exit seen before the unread cleanup-issuing message is judged only once the channel is drained', async () => {
  const exitFirst = (sup) => {
    sup.connected = false;
    sup.emit('exit', null, 'SIGKILL');
    sup.reply({ type: 'cleanup-issuing' });
    sup.emit('disconnect');
  };
  const fake = fakeSupervisorProcess({ start: owns, input: answersBatch, cleanup: exitFirst });
  assert.deepEqual(await batchThrough(fake), { answer: { ended: true, reports: [] }, cleanup: 'requested' });
  const silent = (sup) => {
    sup.connected = false;
    sup.emit('exit', null, 'SIGKILL');
    sup.emit('disconnect');
  };
  assert.deepEqual(await batchThrough(fakeSupervisorProcess({ start: owns, input: answersBatch, cleanup: silent })),
    { withheld: 'supervisor-lost' }, 'killed, drained, never said it issues');
});

test('transport: a first line of any length arrives in pieces', async () => {
  const pad = 'x'.repeat(17 * 1048576);
  const line = `{"ended":true,"reports":[],"pad":"${pad}"}\n`;
  const fake = fakeSupervisorProcess({
    start: owns,
    input: (sup) => {
      sup.reply({ type: 'input-written' });
      for (let at = 0; at < line.length; at += 1048576) sup.reply({ type: 'stdout', data: Buffer.from(line.slice(at, at + 1048576)) });
      sup.reply({ type: 'stdout-end' });
      sup.reply({ type: 'executor-exit', code: 0, signal: null });
    },
    cleanup: endsGroup,
  });
  const got = await batchThrough(fake);
  assert.equal(got.answer && got.answer.pad.length, pad.length);
});

test('transport: the supervisor ending any other way than by its own group signal withholds every verdict', async () => {
  for (const [cleanup, why] of [
    [(sup) => { sup.reply({ type: 'cleanup-issuing' }); setImmediate(() => sup.die(0, null)); }, 'exit 0 after saying it issues'],
    [(sup) => { sup.reply({ type: 'cleanup-issuing' }); setImmediate(() => sup.die(null, 'SIGTERM')); }, 'another signal'],
    [(sup) => sup.die(null, 'SIGKILL'), 'killed without saying it issues'],
    [(sup) => sup.reply({ type: 'cleanup-impossible' }), 'no group of its own'],
  ]) {
    const fake = fakeSupervisorProcess({ start: owns, input: answersBatch, cleanup });
    const got = await batchThrough(fake);
    assert.deepEqual(got, { withheld: 'supervisor-lost' }, why);
    assert.equal(verdictsAllowed(got), false, why);
  }
});

test('transport: lost, refused, unasked cleanup or out of protocol before the answer withholds', async () => {
  for (const [script, why] of [
    [{ start: (sup) => sup.die(1, null) }, 'gone before owning'],
    [{ start: owns, input: (sup) => sup.die(null, 'SIGKILL') }, 'gone mid-run'],
    [{ start: owns, input: (sup) => sup.reply({ type: 'cleanup-issuing' }) }, 'ends its group unasked'],
    [{ start: (sup) => sup.reply({ type: 'stdout', data: Buffer.from(LINE) }) }, 'output before ownership'],
    [{ start: owns, input: (sup) => { answersBatch(sup); sup.reply({ type: 'executor-exit', code: 0, signal: null }); } }, 'a second exit'],
  ]) {
    const fake = fakeSupervisorProcess({ cleanup: endsGroup, ...script });
    const got = await batchThrough(fake);
    assert.deepEqual(got, { withheld: 'supervisor-lost' }, why);
  }
  const refused = fakeSupervisorProcess({ start: (sup) => sup.reply({ type: 'refused' }), cleanup: endsGroup });
  assert.deepEqual(await batchThrough(refused), { withheld: 'ownership-unconfirmed' });
  assert.deepEqual(refused.made[0].got.map((m) => m.type), ['start', 'cleanup'], 'no input without ownership');
});

test('transport: an executor that could not start, its group then ended, is no answer ({}), as executeBatch gives', async () => {
  const fake = fakeSupervisorProcess({ start: (sup) => sup.reply({ type: 'not-started' }), cleanup: endsGroup });
  const got = await batchThrough(fake);
  assert.deepEqual(got, { cleanup: 'requested' });
  assert.equal(got.answer, undefined);
});

test('transport: Windows and unlisted platforms are unavailable before any supervisor is started', async () => {
  for (const platform of ['win32', 'freebsd', null]) {
    const fake = fakeSupervisorProcess({ start: owns });
    assert.deepEqual(await batchThrough(fake, platform), { unavailable: 'platform' });
    assert.throws(() => makeLaunch({ platform, spawnSupervisor: fake.spawnSupervisor })(['run-batch'], 'the-root'), /unavailable/);
    assert.equal(fake.made.length, 0, String(platform));
  }
});

test('transport: a closed channel at start is loss, and nothing is sent', async () => {
  const sup = new EventEmitter();
  sup.connected = false;
  sup.send = () => assert.fail('nothing is sent on a closed channel');
  sup.unref = () => {};
  sup.disconnect = () => {};
  const transport = connect(sup, ['run-batch'], 'the-root');
  await transport.lost;
  assert.equal(await transport.requestCleanup(), 'lost');
});

test('planted: an exit by any signal taken as the group ended', async () => {
  const damaged = planted('prototype-supervisor-transport.js', "exitedWith.signal === 'SIGKILL'", 'true');
  const script = { start: owns, input: answersBatch, cleanup: (sup) => { sup.reply({ type: 'cleanup-issuing' }); setImmediate(() => sup.die(0, null)); } };
  assert.deepEqual(await batchThrough(fakeSupervisorProcess(script)), { withheld: 'supervisor-lost' });
  assert.deepEqual(await batchThrough(fakeSupervisorProcess(script), 'linux', damaged),
    { answer: { ended: true, reports: [] }, cleanup: 'requested' }, 'the check can fail');
});

test('verdictsAllowed: withheld and unavailable results give no verdict, unavailable included', () => {
  assert.equal(verdictsAllowed({ withheld: 'cleanup-unconfirmed' }), false);
  assert.equal(verdictsAllowed({ unavailable: 'platform' }), false);
  assert.equal(verdictsAllowed({ timedOut: true, cleanup: 'requested' }), true);
  assert.equal(verdictsAllowed({ cleanup: 'requested' }), true);
});

// ---------- Static checks. ----------

test('static: the parent side holds no process id, sends no signal, has no fallback', () => {
  for (const file of ['prototype-supervisor-transport.js', 'prototype-supervised-executor.js']) {
    const text = code(file);
    for (const forbidden of ['process.kill', '.kill(', '.pid', 'endTree', 'killGroup', "'./processes'", 'shell', 'exec(', 'taskkill', 'powershell']) {
      assert.ok(!text.includes(forbidden), `${file}: ${forbidden}`);
    }
  }
});

test('static: the supervisor signals only its own group, by its own id, in exactly two places', () => {
  const text = code('prototype-unix-supervisor.js');
  const kills = text.match(/\bkill\([^)]*\)/g) || [];
  assert.deepEqual(kills, ['kill(-process.pid, 0)', "kill(-process.pid, 'SIGKILL')"]);
  assert.equal((text.match(/\.pid\b/g) || []).length, 2, 'no id but its own');
  assert.ok(!/\bchild\.pid|\.kill\(\s*[^-]/.test(text));
  assert.ok(text.includes("detached: false, windowsHide: true, stdio: ['pipe', 'pipe', 'ignore', 'pipe']"), 'executor undetached, descriptor 3 overwritten');
  assert.ok(!text.includes('shell') && !text.includes('exec('));
  assert.ok(/if \(process\.platform === 'win32'[^\n]*process\.exit\(2\)/.test(text), 'Windows refused before anything starts');
});

test('static: the supervisor is started detached, by the same runtime, with only the channel', () => {
  const text = code('prototype-supervisor-transport.js');
  assert.ok(text.includes("spawn(process.execPath, [path.join(__dirname, 'prototype-unix-supervisor.js')]"));
  assert.ok(text.includes("detached: true, stdio: ['ignore', 'ignore', 'ignore', 'ipc']"));
  assert.ok(!text.includes('fork('), 'no execArgv inherited through fork');
});

test('static: nothing published requires a prototype', () => {
  for (const file of fs.readdirSync(__dirname)) {
    if (!file.endsWith('.js') || file.startsWith('prototype-') || file.startsWith('test-prototype-')) continue;
    assert.ok(!/require\([^)]*prototype-/.test(source(file)), file);
  }
});
