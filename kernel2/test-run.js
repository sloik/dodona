'use strict';
// Tests of the run command's first parts (project-run.js): its additions to step 1, and
// the plan of step 10. Run alone: node --test kernel2/test-run.js
//
// Each refusal starts from an input that is accepted (the control) and breaks one rule,
// so that rule alone stands between it and acceptance: a guard removed turns its test
// red. Guards are removed for real, in a disposable copy, at the end.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  preflight, preflightBytes, diskName, planOf, countsOf, planRun, closeSessions, afterClosing, startCheck, exchange, checkAll, batchWait,
  executeBatch,
} = require('./project-run');
const { runKey } = require('./check');
const crypto = require('node:crypto');
const { Stop, projectStatus } = require('./project-status');
const ledgerFile = require('./ledger-file');
const { identityOf } = require('./identity');

const noLinks = process.platform === 'win32';

// A project with one provider's code, a folder for the run's ledger and one for the
// owner's; no ledger exists yet.
function project() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'kernel2-run-'));
  fs.mkdirSync(path.join(root, 'code'));
  fs.writeFileSync(path.join(root, 'code', 'check.py'), 'print(1)\n');
  fs.writeFileSync(path.join(root, 'dodona.toml'), '[project]\n');
  fs.writeFileSync(path.join(root, 'm.txt'), 'm\n');
  fs.mkdirSync(path.join(root, 'l'));
  fs.mkdirSync(path.join(root, 'records'));
  return root;
}

function input(root, change = {}) {
  return {
    root,
    project: 'dodona.toml',
    site: {
      platform: { os: 'linux', arch: 'x86_64' },
      writer: 'w',
      runner: 'r0',
      tools: [],
      providers: { 't.check': { command: ['provider'], code: ['code/check.py'] } },
      deadline_ms: 1000,
    },
    policy: { required: [], min_hard_gates: 1, floors: {}, not_applied: [] },
    policy_source: 'policy.toml',
    ledgers: ['l/run.ledger'],
    owner_ledger: 'records/owner.ledger',
    ledger: 'l/run.ledger',
    executor: ['executor'],
    transcript: 'l/transcript.json',
    ...change,
  };
}

function outcome(asked, run = preflight) {
  try {
    run(asked);
    return 'ready';
  } catch (error) {
    if (error instanceof Stop) return error.reason;
    throw error;
  }
}

function withProject(body) {
  const root = project();
  try {
    body(root);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

test('names compare as NFC of the case-folded NFC', () => {
  assert.equal(diskName('Records/Owner.Ledger'), diskName('records/owner.ledger'));
  assert.equal(diskName('records/ownér.ledger'), diskName('records/ownér.ledger'));
  assert.equal(diskName('straße'), diskName('STRASSE'));
  assert.equal(diskName('É'), 'é'); // composed again after folding
  assert.notEqual(diskName('records/owner.ledger'), diskName('records/owner.ledger.lock'));
});

test('the control: a run input with and without a transcript is accepted', () => {
  withProject((root) => {
    const digests = preflight(input(root));
    assert.deepEqual([...digests.keys()], ['t.check']);
    assert.match(digests.get('t.check'), /^[0-9a-f]{16}$/);
    const without = input(root);
    delete without.transcript;
    assert.equal(outcome(without), 'ready');
    // A ledger listed second, and one already there, are fine.
    fs.writeFileSync(path.join(root, 'l', 'run.ledger'), '');
    assert.equal(outcome(input(root, { ledgers: ['l/a.ledger', 'l/run.ledger'] })), 'ready');
  });
});

test('ledger: one of ledgers, relative, and never the owner\'s by name', () => {
  withProject((root) => {
    const owner = 'records/owner.ledger';
    for (const [change, why] of [
      [{ ledgers: 5 }, 'ledgers that are not a list'],
      [{ ledgers: ['l/run.ledger', 7] }, 'a ledger that is not a string'],
      [{ ledger: 'l/other.ledger' }, 'a ledger not listed among the ledgers'],
      [{ ledger: undefined }, 'no ledger'],
      [{ ledger: '/l/run.ledger', ledgers: ['/l/run.ledger'] }, 'a ledger that is not relative'],
      [{ ledger: owner, ledgers: [owner] }, "the owner's ledger, not yet written"],
      [{ ledger: 'Records/owner.ledger', ledgers: ['Records/owner.ledger'] }, "the owner's ledger in other case"],
      [{ ledger: 'records/ownér.ledger', ledgers: ['records/ownér.ledger'], owner_ledger: 'records/ownér.ledger' },
        "the owner's ledger in the other Unicode form"],
      [{ owner_ledger: 7 }, 'an owner ledger that is not a string'],
    ]) {
      const asked = input(root, change);
      if (change.ledger === undefined && Object.hasOwn(change, 'ledger')) delete asked.ledger;
      assert.equal(outcome(asked), 'bad-input', why);
    }
  });
});

test('ledger: never the owner\'s as the operating system identifies files', () => {
  withProject((root) => {
    fs.writeFileSync(path.join(root, 'records', 'owner.ledger'), '');
    fs.linkSync(path.join(root, 'records', 'owner.ledger'), path.join(root, 'l', 'run.ledger'));
    assert.equal(outcome(input(root)), 'bad-input', 'a hard link to the owner\'s ledger');
  });
  withProject((root) => {
    // The same bytes in another file are another ledger.
    fs.writeFileSync(path.join(root, 'records', 'owner.ledger'), '');
    fs.writeFileSync(path.join(root, 'l', 'run.ledger'), '');
    assert.equal(outcome(input(root)), 'ready');
  });
});

test('ledger: reached without a link', { skip: noLinks }, () => {
  withProject((root) => {
    fs.mkdirSync(path.join(root, 'real'));
    fs.symlinkSync(path.join(root, 'real'), path.join(root, 'lk'));
    assert.equal(outcome(input(root, { ledger: 'lk/run.ledger', ledgers: ['lk/run.ledger'] })), 'bad-input', 'behind a linked folder');
    fs.writeFileSync(path.join(root, 'real', 'run.ledger'), '');
    fs.symlinkSync(path.join(root, 'real', 'run.ledger'), path.join(root, 'l', 'run.ledger'));
    assert.equal(outcome(input(root)), 'bad-input', 'itself a link');
  });
});

test('executor: a non-empty list of strings, none holding a NUL', () => {
  withProject((root) => {
    for (const executor of [undefined, [], 'executor', [7], ['run\u0000x'], ['a', 'b\u0000']]) {
      const asked = input(root, { executor });
      if (executor === undefined) delete asked.executor;
      assert.equal(outcome(asked), 'bad-input', JSON.stringify(executor));
    }
    assert.equal(outcome(input(root, { executor: ['', 'x'] })), 'ready', 'an empty word is still a string');
  });
});

test('transcript: by name, no ledger, no ledger\'s lock and not the project file', () => {
  withProject((root) => {
    for (const [transcript, change, why] of [
      [null, {}, 'given, and not a path'],
      ['', {}, 'empty'],
      ['trans\u0000cript.json', {}, 'a NUL'],
      ['l/../t.json', {}, 'a dot segment'],
      ['l/run.ledger', {}, 'a ledger'],
      ['l/RUN.ledger', {}, 'a ledger in other case'],
      ['l/run.ledger.lock', {}, "a ledger's lock"],
      ['l/run.ledger.LOCK', {}, "a ledger's lock in other case"],
      ['l/a.ledger', { ledgers: ['l/a.ledger', 'l/run.ledger'] }, 'another ledger'],
      ['records/owner.ledger', {}, "the owner's ledger"],
      ['records/owner.ledger.lock', {}, "the owner's ledger's lock"],
      ['l/rún.ledger', { ledgers: ['l/rún.ledger'], ledger: 'l/rún.ledger' }, 'a ledger in the other Unicode form'],
      ['l/PROJ.toml', { project: 'l/proj.toml' }, 'the project file in other case'],
    ]) {
      assert.equal(outcome(input(root, { transcript, ...change })), 'bad-input', why);
    }
  });
});

test('transcript: a new file in a folder that is there', () => {
  withProject((root) => {
    assert.equal(outcome(input(root, { transcript: 'm.txt' })), 'bad-input', 'a file that is there');
    assert.equal(outcome(input(root, { transcript: 'nowhere/t.json' })), 'bad-input', 'a folder that is not there');
    assert.equal(outcome(input(root, { transcript: 'm.txt/t.json' })), 'bad-input', 'under a file');
    assert.equal(outcome(input(root, { transcript: 'l' })), 'bad-input', 'a folder');
    assert.equal(outcome(input(root, { transcript: 't.json' })), 'ready', 'at the root');
  });
});

test('transcript: reached without a link, and a link to nothing is there', { skip: noLinks }, () => {
  withProject((root) => {
    fs.mkdirSync(path.join(root, 'real'));
    fs.symlinkSync(path.join(root, 'real'), path.join(root, 'lk'));
    assert.equal(outcome(input(root, { transcript: 'lk/t.json' })), 'bad-input', 'behind a linked folder');
    fs.symlinkSync(path.join(root, 'missing'), path.join(root, 'l', 't.json'));
    assert.equal(outcome(input(root, { transcript: 'l/t.json' })), 'bad-input', 'a link to nothing');
  });
});

test('the run\'s fields come before the status command\'s step 1', { skip: noLinks || process.getuid?.() === 0 }, () => {
  withProject((root) => {
    // Status step 1 alone: root not a folder, and no path resolved against the working folder.
    assert.equal(outcome(input('')), 'bad-input');
    assert.equal(outcome(input('', { transcript: 'm.txt' })), 'bad-input');
    // A code file that cannot be read is unreadable-file at the status command's step 1 ...
    fs.chmodSync(path.join(root, 'code', 'check.py'), 0o000);
    try {
      assert.equal(outcome(input(root)), 'unreadable-file');
      // ... but a run field broken as well is found first.
      assert.equal(outcome(input(root, { executor: [] })), 'bad-input');
      assert.equal(outcome(input(root, { transcript: 'm.txt' })), 'bad-input');
      assert.equal(outcome(input(root, { ledger: 'l/other.ledger' })), 'bad-input');
    } finally {
      fs.chmodSync(path.join(root, 'code', 'check.py'), 0o644);
    }
  });
});

test('the bytes of standard input to ready or a refusal', () => {
  withProject((root) => {
    assert.equal(preflightBytes(Buffer.from('{"root":')).refused, 'bad-input');
    assert.equal(preflightBytes(Buffer.from('[]')).refused, 'bad-input');
    const refused = preflightBytes(Buffer.from(JSON.stringify(input(root, { executor: [] }))));
    assert.deepEqual(Object.keys(refused), ['refused', 'detail']);
    assert.ok(preflightBytes(Buffer.from(`${JSON.stringify(input(root))}\n`)).ready instanceof Map);
  });
});

test('a segment ending in a dot or a space: always in the ledgers written and excluded, with a transcript in all it is compared with', () => {
  withProject((root) => {
    const without = (change) => {
      const asked = input(root, change);
      delete asked.transcript;
      return outcome(asked);
    };
    // Always: the run's ledger and the owner's.
    for (const ledger of ['l/run.ledger.', 'l/run.ledger ', 'l./run.ledger', 'l /run.ledger']) {
      assert.equal(without({ ledger, ledgers: [ledger] }), 'bad-input', JSON.stringify(ledger));
    }
    for (const owner of ['records/owner.ledger.', 'records/owner.ledger ', 'records./owner.ledger']) {
      assert.equal(without({ owner_ledger: owner }), 'bad-input', JSON.stringify(owner));
    }
    // With a transcript: it, every ledger listed and the project file.
    for (const [change, why] of [
      [{ transcript: 'l/t.json.' }, 'the transcript'],
      [{ transcript: 'l/t.json ' }, 'the transcript, a space'],
      [{ ledgers: ['l/run.ledger', 'x/other.ledger.'] }, 'another ledger listed'],
      [{ ledgers: ['l/run.ledger', 'x /other.ledger'] }, 'another ledger listed, a folder'],
      [{ project: 'dodona.toml.' }, 'the project file'],
      [{ project: 'p /dodona.toml' }, 'the project file, a folder'],
    ]) {
      assert.equal(outcome(input(root, change)), 'bad-input', why);
    }
    // Without a transcript, the other ledgers listed and the project are not judged so.
    assert.equal(without({ ledgers: ['l/run.ledger', 'x/other.ledger.'] }), 'ready');
    assert.equal(without({ project: 'dodona.toml.' }), 'ready');
    // A dot or a space elsewhere in a segment is fine.
    for (const ledger of ['l/.run.ledger', 'l/run..ledger', 'l/run ledger', 'l/ run.ledger']) {
      assert.equal(outcome(input(root, { ledger, ledgers: [ledger] })), 'ready', JSON.stringify(ledger));
    }
    assert.equal(outcome(input(root, { transcript: 'l/.t.json' })), 'ready');
  });
});

test('planted: a run ledger ending in a dot is let through once only the owner\'s is judged', () => {
  const damaged = planted('endsInDotOrSpace(ledger) || endsInDotOrSpace(ownerRel)', 'endsInDotOrSpace(ownerRel)').preflight;
  withProject((root) => {
    const asked = input(root, { ledger: 'l/run.ledger.', ledgers: ['l/run.ledger.'] });
    delete asked.transcript;
    assert.equal(outcome(asked), 'bad-input');
    assert.equal(outcome(asked, damaged), 'ready');
  });
});

test('planted: with a transcript, a project file ending in a dot is let through once it is not spelt-checked', () => {
  const damaged = planted('...(isRelative(project) ? [project] : [])', '').preflight;
  withProject((root) => {
    const asked = input(root, { project: 'dodona.toml.' });
    assert.equal(outcome(asked), 'bad-input');
    assert.equal(outcome(asked, damaged), 'ready');
  });
});

// A copy of project-run.js with one guard removed, loaded beside the real modules. The
// needle must be found exactly once, so a plant that changes nothing cannot pass.
function planted(needle, replacement) {
  const source = fs.readFileSync(path.join(__dirname, 'project-run.js'), 'utf8');
  assert.equal(source.split(needle).length, 2, `the needle ${needle} is in project-run.js once`);
  const damaged = source.replace(needle, replacement)
    .replace(/require\('\.\/([^']+)'\)/g, (whole, name) => `require(${JSON.stringify(path.join(__dirname, name))})`);
  const where = fs.mkdtempSync(path.join(os.tmpdir(), 'kernel2-planted-'));
  try {
    fs.writeFileSync(path.join(where, 'project-run.js'), damaged);
    return require(path.join(where, 'project-run.js'));
  } finally {
    fs.rmSync(where, { recursive: true, force: true });
  }
}

test('planted: comparing the owner\'s ledger by exact path lets another spelling through', () => {
  const damaged = planted('diskName(ledger) === diskName(ownerRel)', 'ledger === ownerRel').preflight;
  withProject((root) => {
    const asked = input(root, { ledger: 'Records/owner.ledger', ledgers: ['Records/owner.ledger'] });
    assert.equal(outcome(asked), 'bad-input');
    assert.equal(outcome(asked, damaged), 'ready');
  });
});

test('planted: a transcript checked against ledgers but not their locks takes the owner\'s lock', () => {
  const damaged = planted('[rel, `${rel}.lock`]', '[rel]').preflight;
  withProject((root) => {
    const asked = input(root, { transcript: 'records/owner.ledger.lock' });
    assert.equal(outcome(asked), 'bad-input');
    assert.equal(outcome(asked, damaged), 'ready');
  });
});

// Step 10, the plan. A snapshot as the status command's steps 2 to 10 leave it, given
// as listed (not yet sorted), rejected and the status rules' report.
function snapshotWith(listed, statuses, unchecked = []) {
  const obligations = {};
  for (const [name, status] of Object.entries(statuses)) obligations[name] = status === 'unknown' ? { status, reason: 'never-run' } : { status };
  return { obligations: { listed, unchecked }, report: { obligations } };
}

const MIXED = snapshotWith(
  [{ binding: 'zeta', name: 'a1' }, { binding: 'alpha', name: 'z1' }, { binding: 'alpha', name: 'c1' }, { binding: 'alpha', name: 'b1' }, { binding: 'zeta', name: 'z2' }],
  { a1: 'passed', z1: 'unknown', c1: 'conflict', b1: 'failed', z2: 'unknown' },
  ['ghost', 'z2'],
);

const MIXED_PLAN = {
  obligations: 5,
  check: [{ binding: 'alpha', name: 'z1' }, { binding: 'zeta', name: 'z2' }],
  reused: [{ binding: 'alpha', name: 'b1', status: 'failed' }, { binding: 'alpha', name: 'c1', status: 'conflict' }, { binding: 'zeta', name: 'a1', status: 'passed' }],
  not_checkable: ['ghost', 'z2'],
};

test('plan: unknown is checked, passed, failed and conflict reused, by binding and then name', () => {
  assert.deepEqual(planOf(MIXED), MIXED_PLAN);
  // A name both listed and rejected is checked as listed; one only rejected is only counted.
  const counts = countsOf(planOf(MIXED), ['passed', 'refused']);
  assert.deepEqual(Object.keys(counts), ['obligations', 'reused', 'checked', 'passed', 'failed', 'error', 'unavailable', 'unsupported', 'refused', 'not_checkable']);
  assert.deepEqual(counts, { obligations: 5, reused: 3, checked: 2, passed: 1, failed: 0, error: 0, unavailable: 0, unsupported: 0, refused: 1, not_checkable: 2 });
  assert.throws(() => countsOf(planOf(MIXED), []), /exactly one outcome/);
  assert.throws(() => countsOf(planOf(MIXED), ['passed', 'maybe']), /exactly one outcome/);
});

test('counts: every planned check has an outcome given at its own place', () => {
  const plan = planOf(MIXED); // two checks
  // Holes: `every` and `filter` pass over them, so a list with none given looked complete.
  for (const outcomes of [new Array(2), [, 'passed'], ['passed', ,], Object.assign(new Array(2), { 1: 'failed' })]) { // eslint-disable-line no-sparse-arrays
    assert.equal(outcomes.length, 2);
    assert.throws(() => countsOf(plan, outcomes), /exactly one outcome/, JSON.stringify(outcomes));
  }
  for (const outcomes of [{ length: 2, 0: 'passed', 1: 'passed' }, 'pp', undefined, ['passed', 'passed', 'passed'], ['passed', undefined]]) {
    assert.throws(() => countsOf(plan, outcomes), /exactly one outcome/, String(outcomes));
  }
  // The same outcomes in either order give the same counts, in the contract's key order.
  const counted = countsOf(plan, ['unsupported', 'unavailable']);
  assert.deepEqual(counted, countsOf(plan, ['unavailable', 'unsupported']));
  assert.deepEqual(Object.entries(counted), [['obligations', 5], ['reused', 3], ['checked', 2], ['passed', 0], ['failed', 0], ['error', 0],
    ['unavailable', 1], ['unsupported', 1], ['refused', 0], ['not_checkable', 2]]);
});

test('plan: a listed obligation the report gives no status of its own is a fault, not a plan', () => {
  const listed = [{ binding: 'b', name: 'o1' }, { binding: 'b', name: 'o2' }];
  assert.throws(() => planOf(snapshotWith(listed, { o1: 'passed' })), /no status of its own/, 'missing');
  assert.throws(() => planOf(snapshotWith(listed, { o1: 'passed', o2: 'maybe' })), /no status of its own/, 'not a status');
  // A name an ordinary assignment cannot make an own key of: the report has no entry for it.
  const report = { obligations: {} };
  report.obligations.__proto__ = { status: 'passed' }; // eslint-disable-line no-proto
  assert.equal(Object.hasOwn(report.obligations, '__proto__'), false);
  assert.throws(() => planOf({ obligations: { listed: [{ binding: 'b', name: '__proto__' }], unchecked: [] }, report }), /no status of its own/);
  // Given as its own key, the same name is planned as any other.
  const own = { obligations: JSON.parse('{"__proto__": {"status": "unknown", "reason": "never-run"}}') };
  assert.deepEqual(planOf({ obligations: { listed: [{ binding: 'b', name: '__proto__' }], unchecked: [] }, report: own }).check, [{ binding: 'b', name: '__proto__' }]);
});

test('plan: nothing listed, and everything current, check nothing', () => {
  const none = planOf(snapshotWith([], {}));
  assert.deepEqual(none, { obligations: 0, check: [], reused: [], not_checkable: [] });
  assert.deepEqual(countsOf(none, []), { obligations: 0, reused: 0, checked: 0, passed: 0, failed: 0, error: 0, unavailable: 0, unsupported: 0, refused: 0, not_checkable: 0 });
  const current = planOf(snapshotWith([{ binding: 'b', name: 'o1' }, { binding: 'b', name: 'o2' }], { o1: 'passed', o2: 'failed' }, ['gone']));
  assert.deepEqual(current.check, []);
  assert.deepEqual(countsOf(current, []), { obligations: 2, reused: 2, checked: 0, passed: 0, failed: 0, error: 0, unavailable: 0, unsupported: 0, refused: 0, not_checkable: 1 });
});

test('planted: an unknown status taken as current is never checked', () => {
  const damaged = planted("const CURRENT = ['passed', 'failed', 'conflict'];", "const CURRENT = ['passed', 'failed', 'conflict', 'unknown'];");
  assert.deepEqual(damaged.planOf(MIXED).check, []);
  assert.notDeepEqual(damaged.planOf(MIXED), MIXED_PLAN);
});

test('planted: a conflict taken as no current result is checked again', () => {
  const damaged = planted('if (CURRENT.includes(status)) reused.push',
    "if (CURRENT.includes(status) && status !== 'conflict') reused.push");
  const plan = damaged.planOf(MIXED);
  assert(plan.check.some(({ name }) => name === 'c1'));
  assert.notDeepEqual(plan, MIXED_PLAN);
});

test('planted: obligations taken by name alone come out of binding order', () => {
  const damaged = planted('compareUnits(a.binding, b.binding) || compareUnits(a.name, b.name)', 'compareUnits(a.name, b.name)');
  assert.notDeepEqual(damaged.planOf(MIXED), MIXED_PLAN);
});

// A provider that answers from a file: its manifest, and an enumeration per binding.
const PROVIDER = `'use strict';
const fs = require('node:fs');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const send = (message) => process.stdout.write(JSON.stringify(message) + '\\n');
let buffer = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  buffer += chunk;
  for (let at = buffer.indexOf('\\n'); at >= 0; at = buffer.indexOf('\\n')) {
    const message = JSON.parse(buffer.slice(0, at));
    buffer = buffer.slice(at + 1);
    if (config.log) {
      const seen = { pid: process.pid, type: message.type, id: message.id, binding: message.body && message.body.binding };
      fs.appendFileSync(config.log, JSON.stringify(seen) + '\\n');
    }
    if (message.type === 'hello') send({ type: 'manifest', echo: message.echo, manifest: config.manifest });
    else if (message.type === 'request') send({ type: 'result', id: message.id, capability: message.capability, body: config.answers[message.body.binding] });
    else if (message.type === 'shutdown') process.exit(0);
  }
});
process.stdin.on('end', () => process.exit(0));
`;

function obligation(name, file) {
  return { name, kind: 'check', specified_by: [file], targets: [file], expect: 'holds', config: {}, inputs: [file] };
}

test('plan through the status command\'s own steps and status rules', async () => {
  const root = project();
  try {
    fs.mkdirSync(path.join(root, 'm'));
    fs.mkdirSync(path.join(root, 'n'));
    fs.writeFileSync(path.join(root, 'm', 'a.txt'), 'a\n');
    fs.writeFileSync(path.join(root, 'n', 'b.txt'), 'b\n');
    fs.writeFileSync(path.join(root, 'dodona.toml'), '[project]\nname = "p"\n\n'
      + '[[binding]]\nname = "zeta"\nprovider = "t.check"\ncapabilities = ["obligation.enumerate", "obligation.check"]\nmatch = ["m/*.txt"]\n\n'
      + '[[binding]]\nname = "alpha"\nprovider = "t.check"\ncapabilities = ["obligation.enumerate", "obligation.check"]\nmatch = ["n/*.txt"]\n');
    fs.writeFileSync(path.join(root, 'code', 'provider.js'), PROVIDER);
    fs.writeFileSync(path.join(root, 'code', 'answers.json'), JSON.stringify({
      manifest: { protocol: '0.2', name: 't.check', version: '1.0.0', capabilities: [{ capability: 'obligation.enumerate' }, { capability: 'obligation.check' }], tools: [] },
      answers: {
        zeta: { obligations: [obligation('a1', 'm/a.txt'), obligation('z2', 'm/a.txt')], rejected: [{ name: 'z2' }, { name: 'ghost' }] },
        alpha: { obligations: [obligation('z1', 'n/b.txt'), obligation('c1', 'n/b.txt'), obligation('b1', 'n/b.txt')] },
      },
    }));
    const site = input(root).site;
    const asked = input(root, {
      transcript: undefined,
      site: { ...site, deadline_ms: 20000, providers: { 't.check': { command: [process.execPath, path.join(root, 'code', 'provider.js'), path.join(root, 'code', 'answers.json')], code: ['code/provider.js'] } } },
    });
    delete asked.transcript;

    // Nothing recorded yet: everything listed is checked, by binding and then name.
    const first = await planRun(asked);
    await closeSessions(first.sessions);
    assert.deepEqual(first.plan.check, [
      { binding: 'alpha', name: 'b1' }, { binding: 'alpha', name: 'c1' }, { binding: 'alpha', name: 'z1' },
      { binding: 'zeta', name: 'a1' }, { binding: 'zeta', name: 'z2' }]);
    assert.deepEqual(first.plan.not_checkable, ['ghost', 'z2']);

    // Verdicts under each obligation's own key, as a run records them.
    const record = (name, verdict) => {
      const preimage = first.snapshot.judged.obligations[name].preimage;
      const body = { obligation: name, preimage, core_key: identityOf(preimage), platform: 'linux/x86_64', verdict, writer: 'w' };
      assert.ok(ledgerFile.append({ ledger: path.join(root, 'l', 'run.ledger'), kind: 'evidence', body, wait_ms: 1000 }).appended);
    };
    record('a1', 'passed');
    record('b1', 'failed');
    record('c1', 'passed');
    record('c1', 'failed');

    const second = await planRun(asked);
    await closeSessions(second.sessions);
    assert.deepEqual(second.plan.check, [{ binding: 'alpha', name: 'z1' }, { binding: 'zeta', name: 'z2' }]);
    assert.deepEqual(second.plan.reused, [
      { binding: 'alpha', name: 'b1', status: 'failed' }, { binding: 'alpha', name: 'c1', status: 'conflict' }, { binding: 'zeta', name: 'a1', status: 'passed' }]);
    assert.deepEqual(countsOf(second.plan, ['passed', 'error']),
      { obligations: 5, reused: 3, checked: 2, passed: 1, failed: 0, error: 1, unavailable: 0, unsupported: 0, refused: 0, not_checkable: 2 });

    // The status command, after its split, reports from the same steps what the plan read.
    const status = await projectStatus(Buffer.from(JSON.stringify(asked)));
    assert.equal(status.refused, undefined, status.detail);
    assert.deepEqual(status.report.obligations, second.snapshot.report.obligations);
    assert.deepEqual(status.not_checkable, ['ghost', 'z2']);
    assert.deepEqual(status.ledger, { entries: 4, torn: false });
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

// Step 5 of the run: the sessions kept for checks.

const CHECKER = { name: 'checker', version: '1', digest: `sha256:${'c'.repeat(64)}` };
const MANIFEST = {
  protocol: '0.2', name: 't.check', version: '1.0.0',
  capabilities: [{ capability: 'obligation.enumerate' }, { capability: 'obligation.check', strength: { class: 'c', rank: 'bounded' } }],
  tools: [{ name: 'checker' }],
};

// A project of `bindings` ([name, capabilities, folder]) answered from `answers`, each
// message its providers read logged; the run's input for it.
function sessionProject(root, bindings, answers) {
  fs.writeFileSync(path.join(root, 'dodona.toml'), bindings.map(([name, capabilities, folder]) => `[[binding]]\nname = "${name}"\nprovider = "t.check"\n`
    + `capabilities = [${capabilities.map((c) => `"${c}"`).join(', ')}]\nmatch = ["${folder}/*.txt"]\n`).join('\n'));
  for (const [, , folder] of bindings) {
    fs.mkdirSync(path.join(root, folder), { recursive: true });
    fs.writeFileSync(path.join(root, folder, 'a.txt'), `${folder}\n`);
  }
  fs.writeFileSync(path.join(root, 'code', 'provider.js'), PROVIDER);
  const log = path.join(root, 'messages.log');
  fs.writeFileSync(path.join(root, 'code', 'answers.json'), JSON.stringify({ manifest: MANIFEST, answers, log }));
  const site = input(root).site;
  const asked = input(root, {
    site: {
      ...site,
      tools: [{ name: 'other', version: '2', digest: `sha256:${'d'.repeat(64)}` }, CHECKER],
      deadline_ms: 20000,
      providers: { 't.check': { command: [process.execPath, path.join(root, 'code', 'provider.js'), path.join(root, 'code', 'answers.json')], code: ['code/provider.js'] } },
    },
  });
  delete asked.transcript;
  return { asked, log };
}

// What each provider process read, by process, in order.
function messagesByProcess(log) {
  const by = new Map();
  for (const line of fs.readFileSync(log, 'utf8').split('\n').filter(Boolean)) {
    const seen = JSON.parse(line);
    if (!by.has(seen.pid)) by.set(seen.pid, []);
    by.get(seen.pid).push(seen);
  }
  return by;
}

function processOf(by, binding) {
  const found = [...by.entries()].filter(([, seen]) => seen.some((m) => m.type === 'request' && m.binding === binding));
  assert.equal(found.length, 1, `one process was asked for ${binding}`);
  return found[0];
}

test('the run keeps the enumeration session of a checking binding, as it was; a list-only binding\'s ends at once', async () => {
  const root = project();
  let sessions = [];
  try {
    const zeta = { obligations: [obligation('a1', 'm/a.txt')], rejected: [] };
    const { asked, log } = sessionProject(root, [['zeta', ['obligation.enumerate', 'obligation.check'], 'm'], ['alpha', ['obligation.enumerate'], 'n']],
      { zeta, alpha: { obligations: [obligation('b1', 'n/a.txt')] } });
    const ran = await planRun(asked);
    sessions = ran.sessions;
    // One session kept, the checking binding's, though nothing of it need be reused or not.
    assert.equal(sessions.length, 1);
    const [kept] = sessions;
    assert.equal(kept.binding.name, 'zeta');
    assert.equal(kept.next_id, 2);
    assert.deepEqual(kept.manifest, MANIFEST);
    assert.deepEqual(kept.request, {
      binding: 'zeta', definitions: [], files: [{ path: 'm/a.txt', identity: `sha256:${crypto.createHash('sha256').update('m\n').digest('hex')}` }],
    });
    assert.deepEqual(kept.obligations, zeta.obligations);
    assert.equal(kept.code, ran.digests.get('t.check'));
    assert.deepEqual(kept.provider, { name: 't.check', version: `1.0.0+${kept.code}+r0`, protocol: '0.2' });
    assert.deepEqual(kept.provider, ran.snapshot.judged.obligations.a1.preimage.provider);
    assert.deepEqual(kept.tools, [CHECKER]);
    assert.equal(kept.platform, asked.site.platform);
    assert.equal(kept.offers_check, true);
    assert.equal(kept.child.hasExited, false, 'the kept provider is still running');

    let by = messagesByProcess(log);
    assert.equal(by.size, 2);
    const [keptPid, keptSeen] = processOf(by, 'zeta');
    assert.equal(keptPid, kept.child.pid);
    assert.deepEqual(keptSeen.map((m) => [m.type, m.id]), [['hello', undefined], ['request', '1']], 'no shutdown yet');
    const [, listSeen] = processOf(by, 'alpha');
    assert.deepEqual(listSeen.map((m) => m.type), ['hello', 'request', 'shutdown'], 'the list-only session ended at once');

    // Ended by whoever holds it, once.
    await closeSessions(sessions);
    assert.deepEqual(sessions, []);
    await kept.child.exited;
    assert.equal(kept.child.hasExited, true);
    by = messagesByProcess(log);
    assert.deepEqual(by.get(keptPid).map((m) => m.type), ['hello', 'request', 'shutdown']);
    await closeSessions(sessions);
    assert.deepEqual(messagesByProcess(log).get(keptPid).map((m) => m.type), ['hello', 'request', 'shutdown']);

    // The status command keeps nothing: every session it starts ends after its answer.
    const before = new Set(by.keys());
    const status = await projectStatus(Buffer.from(JSON.stringify(asked)));
    assert.equal(status.refused, undefined, status.detail);
    const after = [...messagesByProcess(log)].filter(([pid]) => !before.has(pid));
    assert.equal(after.length, 2);
    for (const [, seen] of after) assert.deepEqual(seen.map((m) => m.type), ['hello', 'request', 'shutdown']);
  } finally {
    await closeSessions(sessions);
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('a refusal after a session was kept ends it before the refusal is given', async () => {
  for (const [why, answers, reason] of [
    ['a later binding\'s answer', { m: { obligations: [obligation('a1', 'm/a.txt')] }, z: { obligations: 5 } }, 'bad-answer'],
    ['the kept binding\'s own answer', { m: { obligations: [{ ...obligation('a1', 'm/a.txt'), inputs: ['m/nope.txt'] }] }, z: { obligations: [] } }, 'bad-inputs'],
  ]) {
    const root = project();
    try {
      const { asked, log } = sessionProject(root, [['m', ['obligation.enumerate', 'obligation.check'], 'm'], ['z', ['obligation.enumerate'], 'z']], answers);
      await assert.rejects(planRun(asked), (error) => error instanceof Stop && error.reason === reason, why);
      const [, seen] = processOf(messagesByProcess(log), 'm');
      assert.deepEqual(seen.map((m) => m.type), ['hello', 'request', 'shutdown'], why);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  }
});

// A kept session standing in for a real one: ending it logs to `calls`, and fails when
// `fails` is set, as reading the process table can on Windows. No process is behind it.
function standIn(name, calls, fails = false) {
  return {
    binding: { name },
    wire: {
      post(message) {
        calls.push(`${name}:${message.type}`);
        if (fails) throw new Error(`${name} could not be ended`);
      },
      close() {
        calls.push(`${name}:close`);
      },
    },
    child: { pid: undefined, exited: Promise.resolve() },
  };
}

test('closing: a session that cannot be ended stops none after it, and the failures are thrown together, in order', async () => {
  const calls = [];
  const sessions = [standIn('a', calls, true), standIn('b', calls), standIn('c', calls, true)];
  await assert.rejects(closeSessions(sessions), (error) => {
    assert.ok(error instanceof AggregateError);
    assert.deepEqual(error.errors.map((each) => each.message), ['a could not be ended', 'c could not be ended']);
    assert.deepEqual(error.failures.map((each) => each.binding), ['a', 'c']);
    assert.match(error.message, /a \(process undefined\): a could not be ended; c \(process undefined\): c could not be ended/);
    return true;
  });
  assert.deepEqual(calls, ['a:shutdown', 'b:shutdown', 'b:close', 'c:shutdown'], 'each tried once, in order');
  assert.deepEqual(sessions, []);
  // Claimed once: closing again tries nothing.
  await closeSessions(sessions);
  assert.deepEqual(calls, ['a:shutdown', 'b:shutdown', 'b:close', 'c:shutdown']);
});

test('closing on a refusal: the refusal is given as it was, with the failure to end a session beside it', async () => {
  const calls = [];
  const stop = new Stop('bad-answer', 'binding z: the answer does not have the shape the contract gives');
  const given = await afterClosing(stop, [standIn('a', calls, true), standIn('b', calls)]);
  assert.equal(given, stop);
  assert.equal(given.reason, 'bad-answer');
  assert.equal(given.detail, 'binding z: the answer does not have the shape the contract gives');
  assert.ok(given.cleanup instanceof AggregateError);
  assert.deepEqual(given.cleanup.failures.map((each) => each.binding), ['a']);
  assert.deepEqual(calls, ['a:shutdown', 'b:shutdown', 'b:close']);
  // With every session ended, nothing rides along.
  const clean = await afterClosing(new Stop('bad-inputs', 'a1'), [standIn('c', calls)]);
  assert.equal(Object.hasOwn(clean, 'cleanup'), false);
});

test('planted: stopping at the first session that cannot be ended leaves the rest running', async () => {
  const damaged = planted('      failures.push({ binding: session.binding.name, pid: session.child.pid, error });', '      throw error;');
  const calls = [];
  await assert.rejects(damaged.closeSessions([standIn('a', calls, true), standIn('b', calls)]), /a could not be ended/);
  assert.deepEqual(calls, ['a:shutdown'], 'b was never tried');
});

test('planted: a kept session never handed to its holder is left running after a refusal', async () => {
  // The plant gives the refusal without ending the kept sessions, and hands this test
  // the very sessions it left open, so that the test, not a process id, ends them.
  const damaged = planted('    throw await afterClosing(error, sessions);', '    error.leftOpen = sessions;\n    throw error;');
  const root = project();
  let left = [];
  try {
    const { asked, log } = sessionProject(root, [['m', ['obligation.enumerate', 'obligation.check'], 'm'], ['z', ['obligation.enumerate'], 'z']],
      { m: { obligations: [obligation('a1', 'm/a.txt')] }, z: { obligations: 5 } });
    let refusal = null;
    try {
      left = (await damaged.planRun(asked)).sessions; // not expected: the run must refuse
    } catch (error) {
      refusal = error;
      if (Array.isArray(error.leftOpen)) left = error.leftOpen;
    }
    assert.ok(refusal instanceof Stop && refusal.reason === 'bad-answer', String(refusal));
    assert.equal(left.length, 1);
    const [pid, seen] = processOf(messagesByProcess(log), 'm');
    assert.equal(left[0].child.pid, pid, 'the session left open is the provider that was asked');
    assert.equal(left[0].child.hasExited, false, 'left running');
    assert.deepEqual(seen.map((m) => m.type), ['hello', 'request'], 'no shutdown was sent');
  } finally {
    // Whatever was asserted, the plant's leftover is ended (shutdown, a moment to exit,
    // its own process group) and waited for before its folder is removed.
    try {
      const children = left.map((session) => session.child);
      await closeSessions(left);
      const bound = new Promise((resolve) => setTimeout(resolve, 5000).unref());
      await Promise.race([Promise.all(children.map((child) => child.exited)), bound]);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  }
});

// Step 11: checks on kept sessions, with a wire that stands in for a provider. Each
// answer is made from the request it answers; no process is behind it.

const FILE_A = { path: 'm/a.txt', identity: `sha256:${'a'.repeat(64)}` };
const FILE_B = { path: 'm/b.txt', identity: `sha256:${'b'.repeat(64)}` };
const PLATFORM = { os: 'linux', arch: 'x86_64' };

function keptSession(binding, answers, change = {}, pending = false) {
  const sent = [];
  const wire = {
    hasMore() {
      return pending;
    },
    async send(message) {
      sent.push(message);
      return null;
    },
    async next() {
      const answer = answers.shift();
      return answer === undefined ? { reason: 'deadline' } : answer(sent[sent.length - 1]);
    },
  };
  return {
    binding: { name: binding },
    wire,
    sent,
    child: { pid: undefined, exited: Promise.resolve() },
    manifest: MANIFEST,
    next_id: 2,
    request: { binding, definitions: [], files: [FILE_A, FILE_B] },
    obligations: [obligation('a1', 'm/a.txt'), { ...obligation('a2', 'm/b.txt'), defect_of: 'a1' }],
    provider: { name: 't.check', version: '1.0.0+0123456789abcdef+r0', protocol: '0.2' },
    tools: [CHECKER],
    platform: PLATFORM,
    deadline_ms: 1000,
    offers_check: true,
    ...change,
  };
}

const answering = (body) => (request) => ({ message: { type: 'result', id: request.id, capability: 'obligation.check', body } });
const RUN = {
  program: { tool: 'checker', path: 'bin/check' }, args: ['m/a.txt'], inputs: [FILE_A], outputs: [], tools: [{ name: 'checker', digest: CHECKER.digest }], platform: PLATFORM,
};
const FINAL = { verdict: 'passed', strength: { class: 'c', rank: 'bounded' } };

test('a check starts on its binding\'s kept session with what it was kept with, and its own inputs only', async () => {
  const session = keptSession('zeta', [answering({ next: RUN }), answering({ final: FINAL })]);
  const { check, step } = await startCheck([session], { binding: 'zeta', name: 'a1' }, os.tmpdir());
  assert.equal(session.sent.length, 1);
  const [start] = session.sent;
  assert.deepEqual({ ...start, body: undefined }, { type: 'request', id: '2', deadline_ms: 1000, capability: 'obligation.check', body: undefined });
  const { inputs: unused, ...enumerated } = obligation('a1', 'm/a.txt');
  assert.deepEqual(start.body, { op: 'start', obligation: { ...enumerated, binding: 'zeta' }, inputs: [FILE_A], tools: [CHECKER], platform: PLATFORM });
  assert.equal(Object.hasOwn(start.body.obligation, 'inputs'), false);
  assert.equal(start.body.tools, session.tools, 'the tools the session was kept with');
  assert.equal(start.body.platform, session.platform, 'the site\'s own platform object');
  // A run that keeps every host rule is the next step, under its own run key.
  const key = identityOf({ obligation: start.body.obligation, inputs: start.body.inputs });
  assert.deepEqual(step, { outcome: 'next', number: 1, run_key: runKey(key, 1, RUN), run: RUN });
  assert.equal(check.start_id, '2');
  assert.equal(session.next_id, 3);
  // The run's result passed back, and a final within the manifest's ceiling, its strength as given.
  const final = await exchange(check, { op: 'run.result', check: check.start_id, run: 1, report: { end: 'exited' } });
  assert.deepEqual(final, { outcome: 'final', verdict: 'passed', strength: { class: 'c', rank: 'bounded' } });
  assert.equal(session.sent[1].id, '3');
  // An enumerated field beyond the ones read (defect_of) is carried as it was.
  const other = keptSession('zeta', [answering({ next: { ...RUN, args: ['m/b.txt'], inputs: [FILE_B] } })]);
  await startCheck([other], { binding: 'zeta', name: 'a2' }, os.tmpdir());
  assert.equal(other.sent[0].body.obligation.defect_of, 'a1');
  assert.deepEqual(other.sent[0].body.inputs, [FILE_B]);
});

test('checks on two bindings take each its own session and its own ids', async () => {
  const first = keptSession('alpha', [answering({ next: RUN }), answering({ next: RUN })]);
  const second = keptSession('zeta', [answering({ next: RUN })]);
  const sessions = [first, second];
  await startCheck(sessions, { binding: 'zeta', name: 'a1' }, os.tmpdir());
  await startCheck(sessions, { binding: 'alpha', name: 'a1' }, os.tmpdir());
  await startCheck(sessions, { binding: 'alpha', name: 'a1' }, os.tmpdir());
  assert.deepEqual(second.sent.map((m) => [m.id, m.body.obligation.binding]), [['2', 'zeta']]);
  assert.deepEqual(first.sent.map((m) => [m.id, m.body.obligation.binding]), [['2', 'alpha'], ['3', 'alpha']]);
  assert.deepEqual([first.next_id, second.next_id], [4, 3]);
});

test('a binding that does not check, or whose manifest does not offer it, is refused with nothing sent', async () => {
  const offering = keptSession('alpha', []);
  const unoffered = keptSession('zeta', [], { offers_check: false });
  for (const planned of [{ binding: 'listonly', name: 'a1' }, { binding: 'zeta', name: 'a1' }]) {
    assert.deepEqual(await startCheck([offering, unoffered], planned, os.tmpdir()), { check: null, step: { outcome: 'refused', reason: 'check-not-offered' } });
  }
  assert.deepEqual([offering.sent, unoffered.sent], [[], []]);
  assert.deepEqual([offering.next_id, unoffered.next_id], [2, 2]);
});

test('a rule broken refuses one check; the session goes on', async () => {
  for (const [body, reason, runsBefore] of [
    [{}, 'neither-or-both'],
    [{ next: RUN, final: FINAL }, 'neither-or-both'],
    [{ final: FINAL }, 'verdict-without-run', 0],
    [{ next: { ...RUN, env: {} } }, 'env-not-allowed'],
    [{ next: { ...RUN, platform: { os: 'linux', arch: 'arm64' } } }, 'platform-mismatch'],
    [{ next: { ...RUN, inputs: [FILE_B], args: ['m/b.txt'] } }, 'input-not-in-key'],
    [{ next: RUN }, 'too-many-runs', 8],
    [{ final: { verdict: 'passed', strength: { class: 'c', rank: 'exhaustive' } } }, 'strength-above-ceiling', 1],
    [{ final: { verdict: 'unavailable' } }, 'bad-verdict'],
  ]) {
    const session = keptSession('zeta', [answering({ next: RUN }), answering(body)]);
    const { check } = await startCheck([session], { binding: 'zeta', name: 'a1' }, os.tmpdir());
    if (runsBefore !== undefined) check.rules.runs = runsBefore;
    assert.deepEqual(await exchange(check, { op: 'run.result', check: '2', run: 1, report: {} }), { outcome: 'refused', reason }, JSON.stringify(body));
    assert.equal(session.broken, undefined);
    assert.equal(session.next_id, 4);
  }
});

test('a session that breaks refuses the whole run, and is not used again', async () => {
  for (const [answer, reason] of [
    [(request) => ({ message: { type: 'result', id: '9', capability: 'obligation.check', body: { next: RUN } } }), 'wrong-id'],
    [(request) => ({ message: { type: 'error', id: request.id } }), 'provider-error'],
    [(request) => ({ message: { type: 'result', id: request.id, capability: 'obligation.enumerate', body: { next: RUN } } }), 'wrong-capability'],
    [(request) => ({ message: { type: 'result', id: request.id, capability: 'obligation.check', body: 5 } }), 'unexpected'],
    [() => ({ reason: 'deadline' }), 'deadline'],
    [() => ({ reason: 'closed' }), 'closed'],
  ]) {
    const session = keptSession('zeta', [answer]);
    await assert.rejects(startCheck([session], { binding: 'zeta', name: 'a1' }, os.tmpdir()), (error) => error instanceof Stop && error.reason === reason);
    assert.equal(session.broken, reason);
    await assert.rejects(startCheck([session], { binding: 'zeta', name: 'a1' }, os.tmpdir()), /already broken/);
    assert.equal(session.sent.length, 1, 'nothing more is sent on it');
  }
});

test('a provider that spoke while its session was idle breaks it, and nothing is sent', async () => {
  const { PassThrough } = require('node:stream');
  const { Wire } = require('./wire');
  for (const [unsolicited, what] of [
    ['{"type":"result","id":"2","capability":"obligation.check","body":{"next":{}}}\n', 'a whole message, even one that looks like the answer'],
    ['{"type":"res', 'part of a message'],
  ]) {
    const child = { stdout: new PassThrough(), stderr: new PassThrough(), stdin: new PassThrough() };
    const written = [];
    child.stdin.on('data', (data) => written.push(data));
    const wire = new Wire(child, { maxLine: 1048576, maxLog: 1048576, strict: true });
    child.stdout.write(unsolicited);
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(wire.hasMore(), true, what);
    const session = keptSession('zeta', [], { wire });
    await assert.rejects(startCheck([session], { binding: 'zeta', name: 'a1' }, os.tmpdir()), (error) => error instanceof Stop && error.reason === 'unexpected', what);
    assert.equal(session.broken, 'unexpected');
    assert.equal(session.next_id, 2, 'no id taken');
    assert.deepEqual(written, [], `nothing written to the provider: ${what}`);
  }
  // With nothing waiting, the answer to the request is read as before.
  const quiet = keptSession('zeta', [answering({ next: RUN })], {}, false);
  assert.equal((await startCheck([quiet], { binding: 'zeta', name: 'a1' }, os.tmpdir())).step.outcome, 'next');
});

test('planted: a session that is not looked at before sending takes an unsolicited frame for its answer', async () => {
  const damaged = planted("  if (session.wire.hasMore()) brokeOff(session, 'unexpected');\n", '');
  const pending = () => keptSession('zeta', [answering({ next: RUN })], {}, true);
  const kept = pending();
  await assert.rejects(startCheck([kept], { binding: 'zeta', name: 'a1' }, os.tmpdir()), (error) => error instanceof Stop && error.reason === 'unexpected');
  assert.equal(kept.sent.length, 0);
  const missed = pending();
  assert.equal((await damaged.startCheck([missed], { binding: 'zeta', name: 'a1' }, os.tmpdir())).step.outcome, 'next');
  assert.equal(missed.sent.length, 1, 'the damaged copy sent a request');
});

test('planted: every claimed file given as a check\'s inputs, not its own', async () => {
  const damaged = planted('item.inputs.map((rel) => ({ path: rel, identity: files.get(rel) }))', 'session.request.files');
  const session = keptSession('zeta', [answering({ next: RUN })]);
  await damaged.startCheck([session], { binding: 'zeta', name: 'a1' }, os.tmpdir());
  assert.notDeepEqual(session.sent[0].body.inputs, [FILE_A]);
});

// Step 12: batches, with an executor that answers from a script and records each batch.

const RUN_B = { ...RUN, args: ['m/b.txt'], inputs: [FILE_B] };
const EXITED = { end: 'exited', platform: PLATFORM, tools_ran: [{ name: 'checker', digest: CHECKER.digest }] };
const PLAN_TWO = { check: [{ binding: 'alpha', name: 'a1' }, { binding: 'zeta', name: 'a2' }] };

// Two sessions answering in turn, every message they are sent logged in one order.
function twoSessions(alphaAnswers, zetaAnswers) {
  const order = [];
  const sessions = [keptSession('alpha', alphaAnswers), keptSession('zeta', zetaAnswers)];
  for (const session of sessions) {
    const send = session.wire.send;
    session.wire.send = async (message) => {
      order.push([session.binding.name, message.id, message.body.op]);
      return send(message);
    };
  }
  return { sessions, order };
}

// An executor answering each batch with `answer(runs)`, the batches it was given kept.
function scripted(answer) {
  const batches = [];
  const execute = async (batch, waitMs) => {
    batches.push({ batch, waitMs });
    return answer(batch.runs, batches.length);
  };
  return { execute, batches };
}

const reportsFor = (runs, report = EXITED) => ({ answer: { ended: true, reports: runs.map((run) => ({ run_key: run.run_key, report })) } });

test('batches: two bindings, two rounds, reports in any order, passed back in the order the checks started', async () => {
  const { sessions, order } = twoSessions(
    [answering({ next: RUN }), answering({ next: RUN }), answering({ final: FINAL })],
    [answering({ next: RUN_B }), answering({ final: { verdict: 'failed', strength: { class: 'c', rank: 'sampled' } } })],
  );
  // Each run its own valid report, told apart by fields a host does not judge, and the
  // reports given in reverse: each must reach the check whose run_key it names.
  const reportOf = (round, at) => ({ ...EXITED, exit_status: 10 * round + at, log: `round ${round} run ${at}` });
  const { execute, batches } = scripted((runs, round) => ({
    answer: { ended: true, reports: runs.map((run, at) => ({ run_key: run.run_key, report: reportOf(round, at) })).reverse() },
  }));
  const ends = await checkAll(sessions, PLAN_TWO, os.tmpdir(), execute);
  assert.deepEqual(ends, [
    { binding: 'alpha', name: 'a1', outcome: 'passed', strength: { class: 'c', rank: 'bounded' } },
    { binding: 'zeta', name: 'a2', outcome: 'failed', strength: { class: 'c', rank: 'sampled' } },
  ]);
  // One executor call per round: both first runs, in the order the checks started; then alpha's second.
  assert.deepEqual(batches.map(({ batch }) => batch.runs.map((run) => run.number)), [[1, 1], [2]]);
  assert.deepEqual(batches[0].batch.runs.map((run) => run.run), [RUN, RUN_B]);
  assert.equal(batches[0].waitMs, 24 * 60 * 60 * 1000, 'no wall_ms: a day');
  assert.deepEqual(order, [
    ['alpha', '2', 'start'], ['zeta', '2', 'start'],
    ['alpha', '3', 'run.result'], ['zeta', '3', 'run.result'],
    ['alpha', '4', 'run.result'],
  ]);
  // The batch's first run was alpha's, its second zeta's; alpha's second round was alone.
  assert.deepEqual(sessions[0].sent[1].body, { op: 'run.result', check: '2', run: 1, report: reportOf(1, 0) });
  assert.deepEqual(sessions[1].sent[1].body, { op: 'run.result', check: '2', run: 1, report: reportOf(1, 1) });
  assert.deepEqual(sessions[0].sent[2].body, { op: 'run.result', check: '2', run: 2, report: reportOf(2, 0) });
  // Each run's key is its own check's, from what that check was started with.
  const keyOf = (start, number, run) => runKey(identityOf({ obligation: start.body.obligation, inputs: start.body.inputs }), number, run);
  assert.deepEqual(batches[0].batch.runs.map((run) => run.run_key), [keyOf(sessions[0].sent[0], 1, RUN), keyOf(sessions[1].sent[0], 1, RUN_B)]);
  assert.deepEqual(batches[1].batch.runs.map((run) => run.run_key), [keyOf(sessions[0].sent[0], 2, RUN)]);
  assert.notEqual(batches[0].batch.runs[0].run_key, batches[0].batch.runs[1].run_key);
});

test('batches: two checks on one kept session take its ids in turn, each report to its own check', async () => {
  const session = keptSession('alpha', [
    answering({ next: RUN }),
    answering({ next: RUN_B }),
    answering({ final: FINAL }),
    answering({ final: { verdict: 'failed', strength: { class: 'c', rank: 'sampled' } } }),
  ]);
  const reportFor = (at) => ({ ...EXITED, exit_status: at, log: `run ${at}` });
  const { execute, batches } = scripted((runs) => ({
    answer: { ended: true, reports: runs.map((run, at) => ({ run_key: run.run_key, report: reportFor(at) })).reverse() },
  }));
  const ends = await checkAll([session], { check: [{ binding: 'alpha', name: 'a1' }, { binding: 'alpha', name: 'a2' }] }, os.tmpdir(), execute);
  assert.deepEqual(ends, [
    { binding: 'alpha', name: 'a1', outcome: 'passed', strength: { class: 'c', rank: 'bounded' } },
    { binding: 'alpha', name: 'a2', outcome: 'failed', strength: { class: 'c', rank: 'sampled' } },
  ]);
  assert.equal(batches.length, 1);
  assert.deepEqual(batches[0].batch.runs.map((run) => run.run), [RUN, RUN_B]);
  assert.deepEqual(session.sent.map((message) => [message.id, message.body.op, message.body.op === 'start' ? message.body.obligation.name : message.body.check]),
    [['2', 'start', 'a1'], ['3', 'start', 'a2'], ['4', 'run.result', '2'], ['5', 'run.result', '3']]);
  assert.deepEqual(session.sent[2].body, { op: 'run.result', check: '2', run: 1, report: reportFor(0) });
  assert.deepEqual(session.sent[3].body, { op: 'run.result', check: '3', run: 1, report: reportFor(1) });
  assert.equal(session.next_id, 6);
});

test('batches: an answer that is no answer, or that breaks the batch, ends every check in it; one run\'s gap ends its own', async () => {
  const run = (answer) => {
    const { sessions, order } = twoSessions([answering({ next: RUN }), answering({ final: FINAL })], [answering({ next: RUN_B }), answering({ final: FINAL })]);
    return checkAll(sessions, PLAN_TWO, os.tmpdir(), scripted(answer).execute).then((ends) => ({ ends: ends.map((end) => end.outcome), sent: order.length }));
  };
  for (const [answer, outcomes, why] of [
    [() => ({ timedOut: true }), ['error', 'error'], 'not answered in time'],
    [() => ({}), ['unavailable', 'unavailable'], 'could not start, or exited otherwise'],
    [() => ({ answer: [] }), ['unavailable', 'unavailable'], 'not an object'],
    [(runs) => ({ answer: { ended: false, reports: reportsFor(runs).answer.reports } }), ['unavailable', 'unavailable'], 'did not end'],
    [() => ({ answer: { ended: 1, reports: [] } }), ['unavailable', 'unavailable'], 'ended is not true'],
    [() => ({ answer: { ended: true, reports: {} } }), ['unavailable', 'unavailable'], 'reports not a list'],
    [(runs) => ({ answer: { ended: true, reports: [...reportsFor(runs).answer.reports, { run_key: 'sha256:other', report: EXITED }] } }), ['error', 'error'], 'a run not in the batch'],
    [(runs) => ({ answer: { ended: true, reports: [...reportsFor(runs).answer.reports, reportsFor(runs).answer.reports[0]] } }), ['error', 'error'], 'a run twice'],
    [(runs) => ({ answer: { ended: true, reports: [{ run_key: runs[0].run_key }] } }), ['error', 'error'], 'an item without a report'],
    [(runs) => ({ answer: { ended: true, reports: [5, ...reportsFor(runs).answer.reports] } }), ['error', 'error'], 'an item not an object'],
    [(runs) => ({ answer: { ended: true, reports: [{ run_key: runs[1].run_key, report: EXITED }] } }), ['error', 'passed'], 'one run without a report'],
    [(runs) => ({ answer: { ended: true, reports: [{ run_key: runs[0].run_key, report: 'exited' }, { run_key: runs[1].run_key, report: EXITED }] } }), ['error', 'passed'], 'a report not an object'],
    [(runs) => ({ answer: { ended: true, reports: [{ run_key: runs[0].run_key, report: { end: 'unavailable' } }, { run_key: runs[1].run_key, report: EXITED }] } }), ['unavailable', 'passed'], 'a run the executor could not run'],
    [(runs) => ({ answer: { ended: true, reports: [{ run_key: runs[0].run_key, report: { end: 'timed-out' } }, { run_key: runs[1].run_key, report: EXITED }] } }), ['error', 'passed'], 'a run that timed out'],
    [(runs) => reportsFor(runs, { ...EXITED, platform: { os: 'linux', arch: 'arm64' } }), ['error', 'error'], 'another platform'],
    [(runs) => reportsFor(runs, { ...EXITED, tools_ran: [{ name: 'checker', digest: `sha256:${'e'.repeat(64)}` }] }), ['error', 'error'], 'other tools'],
  ]) {
    const { ends, sent } = await run(answer);
    assert.deepEqual(ends, outcomes, why);
    // Only the runs whose report was read as exited were passed back.
    assert.equal(sent, 2 + outcomes.filter((outcome) => outcome === 'passed').length, why);
  }
});

test('batches: a check gets at most eight runs; the ninth it asks for refuses it', async () => {
  const session = keptSession('alpha', Array.from({ length: 9 }, () => answering({ next: RUN })));
  const { execute, batches } = scripted((runs) => reportsFor(runs));
  const ends = await checkAll([session], { check: [{ binding: 'alpha', name: 'a1' }] }, os.tmpdir(), execute);
  assert.deepEqual(ends, [{ binding: 'alpha', name: 'a1', outcome: 'refused', reason: 'too-many-runs' }]);
  assert.deepEqual(batches.map(({ batch }) => batch.runs[0].number), [1, 2, 3, 4, 5, 6, 7, 8]);
});

test('batches: a check refused at its start, or by a rule, takes no run; a session that breaks refuses all', async () => {
  // Not offered, and a final with no run: neither is in any batch.
  const { sessions } = twoSessions([answering({ final: FINAL })], []);
  sessions[1].offers_check = false;
  const { execute, batches } = scripted((runs) => reportsFor(runs));
  assert.deepEqual(await checkAll(sessions, PLAN_TWO, os.tmpdir(), execute), [
    { binding: 'alpha', name: 'a1', outcome: 'refused', reason: 'verdict-without-run' },
    { binding: 'zeta', name: 'a2', outcome: 'refused', reason: 'check-not-offered' },
  ]);
  assert.equal(batches.length, 0, 'nothing to run, no executor');
  // alpha's answer to its report has the wrong id: the run is refused, and zeta is sent nothing more.
  const broken = twoSessions([answering({ next: RUN }), () => ({ message: { type: 'result', id: '9', capability: 'obligation.check', body: { final: FINAL } } })],
    [answering({ next: RUN_B }), answering({ final: FINAL })]);
  await assert.rejects(checkAll(broken.sessions, PLAN_TWO, os.tmpdir(), scripted((runs) => reportsFor(runs)).execute),
    (error) => error instanceof Stop && error.reason === 'wrong-id');
  assert.deepEqual(broken.order, [['alpha', '2', 'start'], ['zeta', '2', 'start'], ['alpha', '3', 'run.result']]);
});

test('batches: the wait is the longest wall_ms, below 0 read as 0, and 60 seconds more, at most a day', () => {
  const runWith = (wall) => ({ run: wall === undefined ? {} : { limits: { wall_ms: wall } } });
  assert.equal(batchWait([runWith(1000), runWith(5000)]), 65000);
  assert.equal(batchWait([runWith(-5)]), 60000);
  assert.equal(batchWait([runWith(1000), runWith(undefined)]), 24 * 60 * 60 * 1000);
  assert.equal(batchWait([runWith(24 * 60 * 60 * 1000)]), 24 * 60 * 60 * 1000);
  assert.equal(batchWait([runWith(1.5)]), 24 * 60 * 60 * 1000);
});

// Step 12's executor command, with a stand-in for the process: no command is started.
// `act(child)` plays the executor once it has been started; `stall` holds its standard
// input unread, `fail` breaks it.
function standInExecutor(act, { stall = false, fail = false, starts = true } = {}) {
  const { PassThrough, Writable } = require('node:stream');
  const started = [];
  const ended = [];
  const start = (argv, cwd) => {
    if (!starts) return { pid: undefined, exited: Promise.resolve() };
    const child = { pid: 4242, stdout: new PassThrough(), stderr: new PassThrough(), exitCode: null, received: [] };
    child.exited = new Promise((resolve) => {
      child.exit = (code) => {
        child.exitCode = code;
        resolve();
      };
    });
    child.stdin = new Writable({
      write(chunk, encoding, callback) {
        child.received.push(chunk);
        if (stall) return;
        callback(fail ? new Error('EPIPE') : null);
      },
    });
    child.stdin.on('error', () => {});
    started.push({ argv, cwd, child });
    setImmediate(() => act(child));
    return child;
  };
  const end = async (child) => {
    ended.push(child);
  };
  return { start, end, started, ended };
}

const ANSWER_LINE = '{"ended":true,"reports":[]}\n';
const answers = (...writes) => (child) => {
  for (const write of writes) {
    if (write === 'eof') child.stdout.end();
    else if (typeof write === 'number') child.exit(write);
    else child.stdout.write(write);
  }
};

test('executor: the batch written whole, the command exited and its output closed, the first line taken', async () => {
  const batch = { runs: [{ number: 1, run_key: 'sha256:k', run: RUN }] };
  const fake = standInExecutor(answers('{"ended":tr', `ue,"reports":[]}\n{"later": 1.5}\n${'x'.repeat(1 << 20)}\nnot json\n`, 'eof', 0));
  const got = await executeBatch(['run-batch', '--flag'], 'the-root', batch, 1000, fake);
  assert.deepEqual(got, { answer: { ended: true, reports: [] } }, 'lines after the first are not read');
  assert.deepEqual(fake.started.map(({ argv, cwd }) => [argv, cwd]), [[['run-batch', '--flag'], 'the-root']]);
  assert.equal(Buffer.concat(fake.started[0].child.received).toString('utf8'), `${JSON.stringify(batch)}\n`);
  assert.deepEqual(fake.ended, [fake.started[0].child], 'its own process group ended, once');
});

test('executor: what does not all happen in time is a timeout', async () => {
  for (const [act, options, why] of [
    [answers(ANSWER_LINE, 0), {}, 'its output kept open (by a process it started)'],
    [answers(ANSWER_LINE, 'eof'), {}, 'it does not exit'],
    [answers(ANSWER_LINE, 'eof', 0), { stall: true }, 'it does not read the batch'],
  ]) {
    const fake = standInExecutor(act, options);
    assert.deepEqual(await executeBatch(['run-batch'], 'the-root', { runs: [] }, 40, fake), { timedOut: true }, why);
    assert.equal(fake.ended.length, 1, why);
  }
});

test('executor: no start, a broken input, another exit status or an unreadable first line is no answer', async () => {
  const notStarted = standInExecutor(() => {}, { starts: false });
  assert.deepEqual(await executeBatch(['nothing-here'], 'the-root', { runs: [] }, 1000, notStarted), {});
  assert.deepEqual(notStarted.ended, [], 'nothing of its own to end');
  for (const [act, options, why] of [
    [answers(ANSWER_LINE, 'eof', 0), { fail: true }, 'the batch could not be written'],
    [answers(ANSWER_LINE, 'eof', 1), {}, 'exit status 1'],
    [answers('{"ended":true,"reports":[]}\r\n', 'eof', 0), {}, 'a carriage return'],
    [answers(Buffer.from('﻿{"ended":true,"reports":[]}\n', 'utf8'), 'eof', 0), {}, 'a byte-order mark'],
    [answers('{"ended":true,"reports":[],"n":1.5}\n', 'eof', 0), {}, 'a fraction'],
    [answers('{"ended":true,"ended":true,"reports":[]}\n', 'eof', 0), {}, 'a key twice'],
    [answers('\n{"ended":true,"reports":[]}\n', 'eof', 0), {}, 'an empty first line'],
    [answers('{"ended":true,"reports":[]}', 'eof', 0), {}, 'no line feed'],
    [answers('[]\n', 'eof', 0), {}, 'not an object'],
    [answers('', 'eof', 0), {}, 'nothing at all'],
  ]) {
    const fake = standInExecutor(act, options);
    assert.deepEqual(await executeBatch(['run-batch'], 'the-root', { runs: [] }, 1000, fake), {}, why);
    assert.equal(fake.ended.length, 1, why);
  }
});

test('executor: a first line of any length is read; an output that fails or closes early is no answer', async () => {
  // Longer than the 16 MiB limit this adapter once had, written in 1 MiB pieces.
  const pad = 'x'.repeat(17 * 1048576);
  const line = `{"ended":true,"reports":[],"pad":"${pad}"}\n`;
  const pieces = [];
  for (let at = 0; at < line.length; at += 1048576) pieces.push(line.slice(at, at + 1048576));
  const long = standInExecutor(answers(...pieces, 'more after it\n', 'eof', 0));
  const got = await executeBatch(['run-batch'], 'the-root', { runs: [] }, 5000, long);
  assert.equal(got.answer && got.answer.pad.length, pad.length);
  assert.equal(long.ended.length, 1);
  for (const [act, why] of [
    // The whole first line is read first, so only the way the output ends tells.
    [(child) => {
      child.stdout.write(ANSWER_LINE);
      setImmediate(() => {
        child.stdout.destroy(new Error('EIO'));
        child.exit(0);
      });
    }, 'an output that fails after a whole first line'],
    [(child) => {
      child.stdout.write(ANSWER_LINE);
      setImmediate(() => {
        child.stdout.destroy();
        child.exit(0);
      });
    }, 'an output closed without coming to its end'],
  ]) {
    const fake = standInExecutor(act);
    assert.deepEqual(await executeBatch(['run-batch'], 'the-root', { runs: [] }, 1000, fake), {}, why);
    assert.equal(fake.ended.length, 1, why);
  }
  // A failed output with no exit: the common deadline wins.
  const hung = standInExecutor((child) => {
    child.stdout.write(ANSWER_LINE);
    setImmediate(() => child.stdout.destroy(new Error('EIO')));
  });
  assert.deepEqual(await executeBatch(['run-batch'], 'the-root', { runs: [] }, 40, hung), { timedOut: true });
  assert.equal(hung.ended.length, 1);
});

test('planted: an answer taken before the command\'s output has closed', async () => {
  const damaged = planted('Promise.all([written, child.exited, outputClosed])', 'Promise.all([written, child.exited])');
  const kept = () => standInExecutor(answers(ANSWER_LINE, 0));
  assert.deepEqual(await executeBatch(['run-batch'], 'the-root', { runs: [] }, 40, kept()), { timedOut: true });
  assert.deepEqual(await damaged.executeBatch(['run-batch'], 'the-root', { runs: [] }, 40, kept()), { answer: { ended: true, reports: [] } });
});

test('planted: a run reported twice taken as reported once', async () => {
  const damaged = planted("    if (reports.has(item.run_key)) return all('error');\n", '');
  const answer = (runs) => ({ answer: { ended: true, reports: [...reportsFor(runs).answer.reports, reportsFor(runs).answer.reports[0]] } });
  const ends = async (module) => {
    const { sessions } = twoSessions([answering({ next: RUN }), answering({ final: FINAL })], [answering({ next: RUN_B }), answering({ final: FINAL })]);
    return (await module.checkAll(sessions, PLAN_TWO, os.tmpdir(), scripted(answer).execute)).map((end) => end.outcome);
  };
  assert.deepEqual(await ends({ checkAll }), ['error', 'error']);
  assert.deepEqual(await ends(damaged), ['passed', 'passed']);
});
