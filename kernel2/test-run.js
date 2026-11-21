'use strict';
// Tests of the run command's first slice, its additions to step 1 (project-run.js).
// Run: node --test kernel2/test-run.js
//
// Each refusal starts from an input that is accepted (the control) and breaks one rule,
// so that rule alone stands between it and acceptance: a guard removed turns its test
// red. Two guards are removed for real, in a disposable copy, at the end.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { preflight, preflightBytes, diskName } = require('./project-run');
const { Stop } = require('./project-status');

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
    return require(path.join(where, 'project-run.js')).preflight;
  } finally {
    fs.rmSync(where, { recursive: true, force: true });
  }
}

test('planted: comparing the owner\'s ledger by exact path lets another spelling through', () => {
  const damaged = planted('diskName(ledger) === diskName(ownerRel)', 'ledger === ownerRel');
  withProject((root) => {
    const asked = input(root, { ledger: 'Records/owner.ledger', ledgers: ['Records/owner.ledger'] });
    assert.equal(outcome(asked), 'bad-input');
    assert.equal(outcome(asked, damaged), 'ready');
  });
});

test('planted: a transcript checked against ledgers but not their locks takes the owner\'s lock', () => {
  const damaged = planted('[rel, `${rel}.lock`]', '[rel]');
  withProject((root) => {
    const asked = input(root, { transcript: 'records/owner.ledger.lock' });
    assert.equal(outcome(asked), 'bad-input');
    assert.equal(outcome(asked, damaged), 'ready');
  });
});
