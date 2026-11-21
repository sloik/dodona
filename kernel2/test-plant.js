'use strict';
// Tests of plant.js, the planted-defect runner (issue 41): it credits only a rejection that repeats, never a
// judge that did not finish, and it removes only its own copy. Every process the runner would start is answered
// by a fake, so no judge, kernel or unit test really runs.
//
//     node --test kernel2/test-plant.js

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const plant = require('./plant.js');

const done = (status, stdout = '', stderr = '') => ({ status, signal: null, stdout, stderr });
const killed = (signal) => ({ status: null, signal, stdout: '', stderr: '' });
// What spawnSync returns when the process could not start, outgrew its buffer or ran out of time.
const failed = (code, signal = null) => ({ status: null, signal, stdout: null, stderr: null, error: Object.assign(new Error(code), { code }) });
const summary = (scenarios, matched, rejected, unfinished = 0) =>
  JSON.stringify({ scenarios, matched, all_matched: matched === scenarios, unfinished, rejected });
const kit = (cases) => done(cases.length ? 1 : 0, cases.map((c) => `MISMATCH ${c}\n`).join('') + summary(3, 3 - cases.length, cases) + '\n');
// What tools/run_ledger_cases.py prints: a line per check, any writer's diagnostics, then the same footer as the
// scenarios with its count under `checks` (issue 41). The options make reports it must not give.
const ledger = (rejected, { status = rejected.length ? 1 : 0, unfinished = 0, key = 'checks', allMatched, before = '' } = {}) =>
  done(status, before + rejected.map((c) => `MISMATCH ${c}: detail\n`).join('') + JSON.stringify({
    [key]: 40, matched: 40 - rejected.length, unfinished, rejected,
    all_matched: allMatched === undefined ? rejected.length === 0 && unfinished === 0 : allMatched,
  }) + '\n');

// A spawn that answers each process, named by its tool, from a queue; one with nothing queued accepts the copy.
function fake(answers, onJudge = () => {}) {
  const calls = [];
  const spawn = (command, args) => {
    const first = path.basename(args[0]);
    const name = args[0] === '--test' ? 'unit' : first === 'dodona-kernel2.js' ? 'loads' : path.basename(first, '.py');
    calls.push(name);
    if (name !== 'unit' && name !== 'loads') onJudge(name, path.dirname(args.find((arg) => arg.endsWith('dodona-kernel2.js'))));
    const queue = answers[name];
    if (queue && queue.length) {
      const answer = queue.shift();
      if (answer instanceof Error) throw answer;
      return answer;
    }
    if (name === 'loads') return done(0, '{"canonical":"{}","sha256":"0"}');
    if (name === 'run_kit') return kit([]);
    return name === 'run_ledger_cases' ? ledger([]) : done(0);
  };
  return { spawn, calls };
}
const judge = (answers, replay = true) => plant.judgeCopy('copy', plant.JUDGES, { replay, spawn: fake(answers).spawn });
const unfinished = (name = 'run_kit', why = 'did not finish') => ({ outcome: 'unfinished', name, why });

test('a scenario rejection that repeats on a named case is credited with the cases that repeated', () => {
  assert.deepEqual(judge({ run_kit: [kit(['plan/a', 'plan/b']), kit(['plan/b', 'plan/c'])] }),
    { outcome: 'rejected', name: 'run_kit', mismatch: true, cases: ['plan/b'] });
});

test('a replay that rejects another case, accepts or does not finish is not credited', () => {
  for (const second of [kit(['plan/b']), kit([]), killed('SIGTERM')]) {
    assert.deepEqual(judge({ run_kit: [kit(['plan/a']), second] }), unfinished('run_kit', 'did not reject again on replay'));
  }
});

test('a scenario judge that did not finish, or whose report is malformed or incomplete, is not credited', () => {
  const cases = {
    launch_error: failed('ENOENT'),
    timeout: failed('ETIMEDOUT', 'SIGTERM'),
    overflow: failed('ENOBUFS'),
    signal: killed('SIGKILL'),
    not_json: done(1, 'MISMATCH plan/a\nnot a report\n'),
    no_output: done(1),
    counts_disagree: done(1, 'MISMATCH plan/a\n' + summary(3, 1, ['plan/a']) + '\n'),
    empty_case: done(1, 'MISMATCH \n' + summary(3, 2, ['']) + '\n'),
    no_scenarios: done(1, summary(0, 0, [])),
    kit_unfinished: done(2, 'UNFINISHED plan/a: kernel exited with 3\n' + summary(3, 2, [], 1) + '\n'),
    exit_without_rejection: done(1, summary(3, 3, []) + '\n'),
    stderr: done(1, kit(['plan/a']).stdout, 'Traceback (most recent call last):\n'),
    checks_key: done(1, 'MISMATCH plan/a\n' + JSON.stringify({ checks: 3, matched: 2, all_matched: false, unfinished: 0, rejected: ['plan/a'] }) + '\n'),
  };
  for (const [name, answer] of Object.entries(cases)) {
    assert.deepEqual(judge({ run_kit: [answer] }), unfinished(), name);
  }
});

test('a ledger rejection that repeats on a named check is credited with the checks that repeated', () => {
  const writer = 'writer 0 gave up at entry 3: the kernel answered {}\n';
  const both = ['torn', 'two kernels appending at once lose nothing'];
  const credited = (cases) => ({ outcome: 'rejected', name: 'run_ledger_cases', mismatch: true, cases });
  assert.deepEqual(judge({ run_ledger_cases: [ledger(['torn']), ledger(['torn'])] }), credited(['torn']));
  assert.deepEqual(judge({ run_ledger_cases: [ledger(both, { before: writer }), ledger(['torn'])] }), credited(['torn']));
  assert.deepEqual(judge({ run_ledger_cases: [ledger(both), ledger(both, { before: writer })] }), credited(both));
});

test('a ledger replay that names another check, accepts or does not finish is not credited', () => {
  for (const second of [ledger(['swapped']), ledger([]), ledger(['torn'], { status: 2, unfinished: 1 }),
    done(1, 'MISMATCH torn: detail\n'), killed('SIGTERM')]) {
    assert.deepEqual(judge({ run_ledger_cases: [ledger(['torn']), second] }), unfinished('run_ledger_cases', 'did not reject again on replay'));
  }
});

test('a ledger report that is partial, malformed or contradictory is not credited', () => {
  const cases = {
    unfinished_after_a_mismatch: ledger(['torn'], { status: 2, unfinished: 1 }),
    unfinished_with_exit_1: ledger(['torn'], { unfinished: 1 }),
    no_footer: done(1, 'MISMATCH torn: detail\n'),
    passed_without_footer: done(0),
    scenario_key: ledger(['torn'], { key: 'scenarios' }),
    exit_1_all_matched: ledger(['torn'], { allMatched: true }),
    exit_0_with_rejection: ledger(['torn'], { status: 0 }),
    exit_1_nothing_rejected: ledger([], { status: 1 }),
    empty_name: ledger(['']),
    stderr: done(1, ledger(['torn']).stdout, 'writer did not finish: OSError\n'),
    signal: killed('SIGTERM'),
    launch_error: failed('ENOENT'),
  };
  for (const [name, answer] of Object.entries(cases)) {
    assert.deepEqual(judge({ run_ledger_cases: [answer] }), unfinished('run_ledger_cases'), name);
  }
});

// The other auxiliary judges name no case the runner reads; run_key_vectors stands for them.
test('an auxiliary rejection must repeat, and one without a mismatch is named as such', () => {
  assert.deepEqual(judge({ run_key_vectors: [done(1, 'MISMATCH key\n'), done(1, 'MISMATCH key\n')] }),
    { outcome: 'rejected', name: 'run_key_vectors', mismatch: true, cases: [] });
  assert.deepEqual(judge({ run_key_vectors: [done(1, 'refused\n'), done(1, 'refused\n')] }),
    { outcome: 'rejected', name: 'run_key_vectors', mismatch: false, cases: [] });
  assert.deepEqual(judge({ run_key_vectors: [done(1, 'MISMATCH key\n'), done(0)] }),
    unfinished('run_key_vectors', 'did not reject again on replay'));
});

test('an auxiliary judge that could not run, was signalled or broke is not credited', () => {
  const cases = {
    usage: done(2),
    signal: killed('SIGTERM'),
    launch_error: failed('ENOENT'),
    traceback: done(1, 'MISMATCH key\n', 'Traceback (most recent call last):\n'),
    disk_full: done(1, 'OSError: [Errno 28] No space left on device\n'),
  };
  for (const [name, answer] of Object.entries(cases)) {
    assert.deepEqual(judge({ run_key_vectors: [answer] }), unfinished('run_key_vectors'), name);
  }
});

test('the unit tests are no judge of the kit, and a copy every judge accepts is clean', () => {
  assert.deepEqual(judge({ unit: [done(1)] }), { outcome: 'rejected', name: plant.UNIT_TESTS, mismatch: false, cases: [] });
  assert.deepEqual(judge({ unit: [killed('SIGTERM')] }), unfinished(plant.UNIT_TESTS));
  assert.deepEqual(judge({}), { outcome: 'clean' });
});

test('the unchanged copy is judged once, without a replay', () => {
  const f = fake({ run_kit: [kit(['plan/a'])] });
  assert.deepEqual(plant.judgeCopy('copy', plant.JUDGES, { replay: false, spawn: f.spawn }),
    { outcome: 'rejected', name: 'run_kit', mismatch: true, cases: ['plan/a'] });
  assert.deepEqual(f.calls, ['run_kit']);
});

// The whole runner, on a made-up kernel with two defects in one file, in a temporary directory of the test's own.
// A sibling directory named like the runner's copies must survive every batch.
function batch(t, answers, options = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'plant-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const source = path.join(dir, 'source');
  const tmp = path.join(dir, 'tmp');
  fs.mkdirSync(source, { recursive: true });
  fs.mkdirSync(path.join(tmp, 'kernel2-plant-other'), { recursive: true });
  fs.writeFileSync(path.join(source, 'rule.js'), 'a = 1; b = 2;');
  const manifest = 'manifest' in options ? options.manifest : JSON.stringify({ defects: [
    { name: 'first', file: 'rule.js', find: 'a = 1', replace: 'a = 0' },
    { name: 'second', file: 'rule.js', find: 'b = 2', replace: 'b = 0' },
  ] });
  if (manifest !== null) fs.writeFileSync(path.join(source, 'defects.json'), manifest);
  const seen = [];
  const removed = [];
  const removedPaths = [];
  const pauses = [];
  const lines = [];
  let failures = options.removeFails === true ? Infinity : options.removeFails || 0;
  const { spawn, calls } = fake(answers, (name, copy) => {
    if (name === 'run_kit') seen.push(fs.readFileSync(path.join(copy, 'rule.js'), 'utf8'));
  });
  // Records what the copy holds when it is removed, so a defect left planted would show, and which path was asked.
  const remove = (copy) => {
    removedPaths.push(copy);
    removed.push(fs.readFileSync(path.join(copy, 'rule.js'), 'utf8'));
    if (failures > 0) {
      failures -= 1;
      throw new Error('EBUSY: resource busy');
    }
    fs.rmSync(copy, { recursive: true, force: true });
  };
  const code = plant.main({ spawn, source, tmp, only: [], otherKernel: source, log: (line) => lines.push(line), remove,
    pause: (ms) => pauses.push(ms), ...options.main });
  return { code, seen, removed, removedPaths, pauses, calls, tmp, left: fs.readdirSync(tmp).sort(),
    report: JSON.parse(lines[lines.length - 1]), verdicts: lines.slice(0, -1) };
}

const bothCaught = () => ({ run_kit: [kit([]), kit(['plan/a']), kit(['plan/a']), kit(['plan/b']), kit(['plan/b'])] });

test('a batch credits rejections that repeat, restores each defect and removes only its own copy', (t) => {
  const run = batch(t, bothCaught());
  assert.equal(run.code, 0);
  assert.deepEqual([run.report.caught, run.report.unfinished, run.report.all_caught, run.report.cleaned_up], [2, 0, true, true]);
  assert.deepEqual(run.seen, ['a = 1; b = 2;', 'a = 0; b = 2;', 'a = 0; b = 2;', 'a = 1; b = 0;', 'a = 1; b = 0;']);
  assert.deepEqual(run.removed, ['a = 1; b = 2;']);
  assert.deepEqual(run.left, ['kernel2-plant-other']);
});

test('a defect whose replay rejects another case is unfinished, not caught', (t) => {
  const run = batch(t, { run_kit: [kit([]), kit(['plan/a']), kit(['plan/a']), kit(['plan/a']), kit(['plan/b'])] });
  assert.equal(run.code, 2);
  assert.deepEqual([run.report.caught, run.report.unfinished, run.report.all_caught], [1, 1, false]);
  assert.match(run.verdicts[1], /^UNFINISHED/);
  assert.deepEqual(run.left, ['kernel2-plant-other']);
});

test('a defect only the unit tests reject is still missed by the kit', (t) => {
  const run = batch(t, { run_kit: [kit([]), kit(['plan/a']), kit(['plan/a'])], unit: [done(0), done(1)] });
  assert.equal(run.code, 1);
  assert.deepEqual([run.report.caught, run.report.missed, run.report.unfinished], [1, 1, 0]);
  assert.match(run.verdicts[1], /^MISSED by the kit/);
});

test('a copy whose load check cannot run is unfinished, and one that does not load is broken', (t) => {
  const run = batch(t, { loads: [killed('SIGTERM'), done(1)] });
  assert.equal(run.code, 2);
  assert.deepEqual([run.report.caught, run.report.unfinished, run.report.broken], [0, 1, 1]);
  assert.match(run.verdicts[0], /^UNFINISHED/);
  assert.match(run.verdicts[1], /^BROKEN/);
  assert.deepEqual(run.removed, ['a = 1; b = 2;']);
});

test('a judge that throws restores the defect and removes the copy', (t) => {
  const run = batch(t, { run_kit: [kit([]), new Error('the judge broke')] });
  assert.equal(run.code, 2);
  assert.deepEqual([run.report.all_caught, run.report.finished], [false, false]);
  assert.deepEqual(run.removed, ['a = 1; b = 2;']);
  assert.deepEqual(run.left, ['kernel2-plant-other']);
});

test('a copy that cannot be removed is tried a bounded number of times and leaves the batch unfinished', (t) => {
  const run = batch(t, bothCaught(), { removeFails: true });
  assert.equal(run.code, 2);
  assert.deepEqual([run.report.caught, run.report.all_caught, run.report.cleaned_up], [2, false, false]);
  assert.equal(run.removedPaths.length, plant.REMOVE_ATTEMPTS);
  assert.equal(run.pauses.length, plant.REMOVE_ATTEMPTS - 1);
  assert.match(run.verdicts[run.verdicts.length - 1], /^UNFINISHED: the temporary copy .* could not be removed/);
});

test('a removal that fails once is tried again, on the exact copy the run made and nothing else', (t) => {
  const run = batch(t, bothCaught(), { removeFails: 1 });
  assert.equal(run.code, 0);
  assert.deepEqual([run.report.all_caught, run.report.cleaned_up], [true, true]);
  assert.equal(run.removedPaths.length, 2);
  assert.equal(run.removedPaths[0], run.removedPaths[1]);
  assert.equal(path.dirname(run.removedPaths[0]), run.tmp);
  assert.match(path.basename(run.removedPaths[0]), /^kernel2-plant-/);
  assert.notEqual(path.basename(run.removedPaths[0]), 'kernel2-plant-other');
  assert.deepEqual(run.left, ['kernel2-plant-other']);
});

test('a unit-test run that did not finish is unfinished, not missed', (t) => {
  // The first defect is caught by the scenario judge; every judge accepts the second and its unit tests are killed.
  for (const unit of [killed('SIGTERM'), failed('ETIMEDOUT', 'SIGTERM'), failed('ENOENT')]) {
    const run = batch(t, { run_kit: [kit([]), kit(['plan/a']), kit(['plan/a'])], unit: [done(0), unit] });
    assert.equal(run.code, 2);
    assert.deepEqual([run.report.caught, run.report.missed, run.report.unfinished], [1, 0, 1]);
    assert.match(run.verdicts[1], /^UNFINISHED \(node --test did not finish\)/);
  }
});

test('a provisional auxiliary rejection cannot finish a batch successfully', (t) => {
  const wrong = () => done(1, 'MISMATCH key\n');
  const run = batch(t, { run_kit: [kit([]), kit([]), kit(['plan/b']), kit(['plan/b'])], run_key_vectors: [done(0), wrong(), wrong()] });
  assert.equal(run.code, 2);
  assert.deepEqual([run.report.caught, run.report.caught_provisionally, run.report.all_caught], [1, 1, false]);
  assert.match(run.verdicts[0], /^caught provisionally \(run_key_vectors, no case named\)/);
  assert.match(run.verdicts[1], /^caught \(run_kit: plan\/b\)/);
});

test('a ledger catch on a repeated named check is caught, not provisionally', (t) => {
  const run = batch(t, { run_kit: [kit([]), kit([]), kit(['plan/b']), kit(['plan/b'])],
    run_ledger_cases: [ledger([]), ledger(['torn']), ledger(['torn'])] });
  assert.equal(run.code, 0);
  assert.deepEqual([run.report.caught, run.report.caught_provisionally, run.report.all_caught], [2, 0, true]);
  assert.match(run.verdicts[0], /^caught \(run_ledger_cases: torn\)/);
  assert.match(run.verdicts[1], /^caught \(run_kit: plan\/b\)/);
});

test('a defect list that is missing, corrupt or malformed leaves the run unfinished with nothing copied or judged', (t) => {
  const lists = {
    missing: null,
    not_json: '{"defects": [',
    no_list: JSON.stringify({ defects: {} }),
    not_an_object: 'null',
    entry_not_strings: JSON.stringify({ defects: [{ name: 'x', file: 'rule.js', find: 1, replace: '' }] }),
    entry_outside_the_copy: JSON.stringify({ defects: [{ name: 'x', file: '../rule.js', find: 'a', replace: 'b' }] }),
    entry_absolute: JSON.stringify({ defects: [{ name: 'x', file: path.resolve('rule.js'), find: 'a', replace: 'b' }] }),
  };
  for (const [name, manifest] of Object.entries(lists)) {
    const run = batch(t, {}, { manifest });
    assert.equal(run.code, 2, name);
    assert.deepEqual([run.report.finished, run.report.all_caught, run.report.cleaned_up], [false, false, true], name);
    assert.deepEqual([run.calls, run.removedPaths, run.left], [[], [], ['kernel2-plant-other']], name);
    assert.match(run.verdicts[0], /^UNFINISHED: the defect list could not be read/, name);
  }
});

test('a copy that fails part of the way is removed and nothing is planted', (t) => {
  const run = batch(t, {}, { main: { copyTree: (from, to) => {
    fs.writeFileSync(path.join(to, 'rule.js'), 'partial');
    throw new Error('ENOSPC: no space left on device');
  } } });
  assert.equal(run.code, 2);
  assert.deepEqual(run.seen, []);
  assert.deepEqual([run.report.all_caught, run.report.finished, run.report.cleaned_up], [false, false, true]);
  assert.deepEqual(run.removed, ['partial']);
  assert.deepEqual(run.left, ['kernel2-plant-other']);
});

test('an unchanged copy that cannot be judged is unfinished, and one that is rejected fails', (t) => {
  const notJudged = batch(t, { run_kit: [killed('SIGTERM')] });
  assert.deepEqual([notJudged.code, notJudged.report.caught, notJudged.report.finished], [2, 0, false]);
  assert.deepEqual(notJudged.left, ['kernel2-plant-other']);
  const rejected = batch(t, { run_kit: [kit(['plan/a'])] });
  assert.deepEqual([rejected.code, rejected.report.caught, rejected.report.finished], [1, 0, true]);
  assert.deepEqual(rejected.left, ['kernel2-plant-other']);
});
