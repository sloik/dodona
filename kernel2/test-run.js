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
  preflight, preflightBytes, diskName, planOf, countsOf, planRun,
} = require('./project-run');
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
