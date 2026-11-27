'use strict';
// Checks that the judges can fail. Copies kernel2/ to a temporary directory,
// plants each defect from defects.json in the copy one at a time, and runs ALL
// the judges against it.
//
//     node kernel2/plant.js [FILE...]
//     node kernel2/plant.js --shard INDEX COUNT
//
// With FILE names (such as project-status.js), only the defects planted in those files
// are tried; the unchanged copy is still put to every judge first. A shard uses
// zero-based manifest positions and reports only whether its own subset was caught.
//
// Per defect it prints
//   caught      a reporting judge rejected the defective copy with a complete report and,
//               run a second time, rejected it again on a case it named both times; those cases are
//               printed (judges are tried one at a time and the first rejection ends the defect's turn),
//   caught provisionally
//               another auxiliary judge exited 1 both times. These judges name no case the runner
//               can compare, so the catch is not shown to be on the same case and stays
//               provisional for issue 41. It is counted separately in `caught_provisionally`.
//               A provisional rejection with no mismatch is also counted in
//               `caught_without_mismatch`,
//   UNFINISHED  a judge or the unit tests did not finish (could not start, were signalled or ran
//               out of time, printed no complete report, broke, or exited other than 0 or 1), or
//               a rejection did not repeat on the same case: nothing was shown either way (issue 41),
//   MISSED      every judge accepted it, or only the unit tests (node --test) rejected it,
//   STALE       the text to replace was not found exactly once (nothing planted),
//   BROKEN      the defective copy does not even load, so nothing was learned.
// Then a JSON summary. Exit status 0 only if every defect was caught; 2 if anything did not
// finish, the defect list could not be read, or the copy could not be made or removed; 1 otherwise.
//
// The CLI supervisor creates the run's temporary directory. The worker's copy is under that
// directory. A surviving supervisor removes it even if the worker crashes. It publishes the
// worker's summary after cleanup. After a hard stop, tools/recover_plant_batches.py reclaims owned work.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { fork, spawnSync } = require('node:child_process');
const strictJson = require('./strict-json');

const root = path.resolve(__dirname, '..');

const UNIT_TESTS = 'node --test';

// The judges are Python programs. Windows installs Python as `python`, not `python3`.
const PYTHON = process.env.DODONA_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

// The status judge recomputes each report with another kernel's `scenario` command, so
// that this kernel does not certify its own report: the first kernel's, built where its
// own build puts it, or the program DODONA_OTHER_KERNEL names.
const OTHER_KERNEL = process.env.DODONA_OTHER_KERNEL
  || path.join(root, 'kernel', 'target', 'release', process.platform === 'win32' ? 'dodona-kernel.exe' : 'dodona-kernel');
// How many status cases are judged at once.
const STATUS_JOBS = process.env.DODONA_STATUS_JOBS || '3';

// Each judge: a name, the tool, the tool's own arguments before `--`, and the
// arguments after `node <kernel>`. Reporting judges end with a structured footer. `count` names the total
// used for that judge. Host-check and status count their skips separately.
const JUDGES = [
  { name: 'run_kit', tool: 'run_kit.py', args: ['scenario'], count: 'scenarios' },
  { name: 'run_ledger_cases', tool: 'run_ledger_cases.py', args: [], count: 'checks' },
  { name: 'run_key_vectors', tool: 'run_key_vectors.py', args: ['key'], count: 'vectors' },
  { name: 'run_attest_check', tool: 'run_attest_check.py', args: ['scenario'], count: 'cases' },
  { name: 'run_input_cases', tool: 'run_input_cases.py', args: [], count: 'cases' },
  { name: 'run_harness_check', tool: 'run_harness_check.py', args: ['scenario'], count: 'cases' },
  { name: 'run_vectors', tool: 'run_vectors.py', args: ['canonical'], count: 'vectors' },
  { name: 'run_path_vectors', tool: 'run_path_vectors.py', args: ['path', 'path-set'], count: 'vectors' },
  { name: 'run_provider_cases', tool: 'run_provider_cases.py', args: ['session'], count: 'cases' },
  { name: 'run_check_cases', tool: 'run_check_cases.py', args: ['check'], count: 'judged' },
  { name: 'run_status_cases', tool: 'run_status_cases.py', before: ['--jobs', STATUS_JOBS, '--kernel', OTHER_KERNEL], args: ['status'], count: 'judged' },
];

// Which judges a defect in a host module is put to first: the ones meant to catch it,
// because the others are slow. Every judge is still run before a defect is called missed.
const FIRST_JUDGES = {
  'check.js': ['run_check_cases', 'run_provider_cases'],
  'host-rules.js': ['run_check_cases', 'run_provider_cases'],
  'session.js': ['run_provider_cases', 'run_check_cases'],
  'wire.js': ['run_provider_cases', 'run_check_cases'],
  'processes.js': ['run_provider_cases', 'run_check_cases'],
  'project-status.js': ['run_status_cases'],
};

function judgesFor(file) {
  const first = FIRST_JUDGES[file] || [];
  return [...first.map((name) => JUDGES.find((judge) => judge.name === name)), ...JUDGES.filter((judge) => !first.includes(judge.name))];
}

// Did the process run to its own end? spawnSync reports a process that could not start, outgrew
// its buffer or ran out of time in `error`, and one ended by a signal in `signal`.
function ended(run) {
  return !run.error && !run.signal && Number.isInteger(run.status);
}

// Does the copy load? Asks it to canonicalise `{}`; that loads every module. null if the
// question could not be put (node did not start, or was ended from outside).
function loads(copy, spawn = spawnSync) {
  const run = spawn('node', [path.join(copy, 'dodona-kernel2.js'), 'canonical'], { input: '{}', encoding: 'utf8' });
  if (!ended(run)) return null;
  return run.status === 0 && (run.stdout || '').includes('"canonical":"{}"');
}

// Read a reporting judge's final tally. A rejection carries its exact case names.
// A missing, malformed or incomplete tally, a contradictory exit status, or stderr leaves the judge unfinished.
function scenarioVerdict(run, count = 'scenarios') {
  const unfinished = { verdict: 'unfinished' };
  if (!ended(run) || (run.stderr || '') !== '') return unfinished;
  const lines = (run.stdout || '').trimEnd().split(/\r?\n/);
  let report;
  try {
    report = strictJson.read(lines[lines.length - 1]).value;
  } catch {
    return unfinished;
  }
  if (!(report instanceof Map) || report.get('unfinished') !== 0n) return unfinished;
  const total = report.get(count);
  const matched = report.get('matched');
  const rejected = report.get('rejected');
  if (typeof total !== 'bigint' || typeof matched !== 'bigint' || total < 1n || matched < 0n || matched > total
      || !Array.isArray(rejected) || BigInt(rejected.length) !== total - matched
      || rejected.some((name) => typeof name !== 'string' || name.trim() === '')
      || new Set(rejected).size !== rejected.length) return unfinished;
  if (count === 'judged') {
    const cases = report.get('cases');
    const skipped = report.get('skipped');
    if (typeof skipped !== 'bigint' || skipped < 0n || cases !== total + skipped) return unfinished;
  }
  if (run.status === 0 && rejected.length === 0 && report.get('all_matched') === true) return { verdict: 'passed' };
  if (run.status === 1 && rejected.length > 0 && report.get('all_matched') === false) return { verdict: 'rejected', cases: rejected };
  return unfinished;
}

// Another judge's verdict. Each exits 0 when the kernel passes and 1 when it finds the kernel wrong;
// any other ending, a traceback or a full disk means the judge itself did not finish its work.
function auxiliaryVerdict(run) {
  if (!ended(run)) return { verdict: 'unfinished' };
  if (run.status === 0) return { verdict: 'passed' };
  const stdout = run.stdout || '';
  const stderr = run.stderr || '';
  if (run.status !== 1 || stderr.includes('Traceback (most recent call last)')
      || (stdout + stderr).includes('No space left on device')) return { verdict: 'unfinished' };
  return { verdict: 'rejected', mismatch: /MISMATCH/.test(stdout) };
}

function runJudge(judge, copy, spawn) {
  const run = spawn(PYTHON, [path.join('tools', judge.tool), ...(judge.before || []), '--', 'node', path.join(copy, 'dodona-kernel2.js'), ...judge.args], {
    cwd: root,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  return judge.count ? scenarioVerdict(run, judge.count) : auxiliaryVerdict(run);
}

// Puts the copy to the judges one at a time, then to its unit tests. Returns
//   { outcome: 'clean' }                                    every judge and the unit tests accepted it,
//   { outcome: 'rejected', name, mismatch, cases }          the first judge that rejected it (cases are the
//                                                           scenarios, ledger checks, vectors or cases that rejected it),
//   { outcome: 'unfinished', name, why }                    a judge did not finish, or with `replay` its
//                                                           rejection did not happen again on the same case.
// With `replay`, a judge that rejects the copy is run once more, and only a rejection that repeats counts.
function judgeCopy(copy, judges = JUDGES, { replay = false, spawn = spawnSync } = {}) {
  const notFinished = (name) => ({ outcome: 'unfinished', name, why: 'did not finish' });
  const unsteady = (name) => ({ outcome: 'unfinished', name, why: 'did not reject again on replay' });
  for (const judge of judges) {
    const first = runJudge(judge, copy, spawn);
    if (first.verdict === 'unfinished') return notFinished(judge.name);
    if (first.verdict === 'passed') continue;
    if (judge.count) {
      let cases = first.cases;
      if (replay) {
        const again = runJudge(judge, copy, spawn);
        cases = again.verdict === 'rejected' ? first.cases.filter((name) => again.cases.includes(name)) : [];
        if (cases.length === 0) return unsteady(judge.name);
      }
      return { outcome: 'rejected', name: judge.name, mismatch: true, cases };
    }
    let mismatch = first.mismatch;
    if (replay) {
      const again = runJudge(judge, copy, spawn);
      if (again.verdict !== 'rejected') return unsteady(judge.name);
      mismatch = mismatch && again.mismatch;
    }
    return { outcome: 'rejected', name: judge.name, mismatch, cases: [] };
  }
  // Last: the unit tests of the copy, run against the repository's kit files. They are not a judge
  // of the kit, so a defect only they reject is reported as missed by the kit.
  const tests = spawn('node', ['--test', path.join(copy, 'test.js')], { env: { ...process.env, DODONA_ROOT: root }, encoding: 'utf8' });
  if (!ended(tests)) return notFinished(UNIT_TESTS);
  if (tests.status !== 0) return { outcome: 'rejected', name: UNIT_TESTS, mismatch: false, cases: [] };
  return { outcome: 'clean' };
}

// The verdict on one planted copy, counted in `counts`.
function judgeDefect(copy, defect, counts, spawn) {
  const load = loads(copy, spawn);
  if (load === null) {
    counts.unfinished += 1;
    return 'UNFINISHED (the copy could not be started)';
  }
  if (!load) {
    counts.broken += 1;
    return 'BROKEN';
  }
  const result = judgeCopy(copy, judgesFor(defect.file), { replay: true, spawn });
  if (result.outcome === 'clean') {
    counts.missed += 1;
    return 'MISSED';
  }
  // Anything that did not finish, the unit tests included, is unfinished before it can be missed: a unit-test
  // run that was signalled, timed out or could not start showed nothing either way.
  if (result.outcome === 'unfinished') {
    counts.unfinished += 1;
    return `UNFINISHED (${result.name} ${result.why})`;
  }
  if (result.name === UNIT_TESTS) {
    // Every judge of the kit accepted the copy and only the unit tests rejected it.
    counts.missed += 1;
    return 'MISSED by the kit (only node --test rejects it)';
  }
  if (result.cases.length) {
    if (Object.hasOwn(defect, 'witness') && !result.cases.some((name) => `${result.name}: ${name}` === defect.witness)) {
      counts.missed += 1;
      return `MISSED (the named witness did not reject on both runs: ${defect.witness})`;
    }
    counts.caught += 1;
    return `caught (${result.name}: ${result.cases.join(', ')})`;
  }
  // An auxiliary judge names no case the runner can compare between the two runs, so its catch is provisional
  // for issue 41: it repeated its exit 1, not shown to be on the same case.
  counts.caught_provisionally += 1;
  if (result.mismatch) return `caught provisionally (${result.name}, no case named)`;
  counts.caught_without_mismatch += 1;
  return `caught provisionally (${result.name} exited 1 without a mismatch)`;
}

// Runs the batch and returns the exit status. Every argument is for tests; the defaults are the real run.
function main({
  spawn = spawnSync,
  source = __dirname,
  tmp = os.tmpdir(),
  only = process.argv.slice(2),
  otherKernel = OTHER_KERNEL,
  log = console.log,
  emitSummary = (summary) => log(JSON.stringify(summary)),
  copyTree = (from, to) => fs.cpSync(from, to, { recursive: true }),
  remove = removeTree,
  pause = sleep,
} = {}) {
  if (!fs.existsSync(otherKernel)) {
    log(`no kernel to recompute status reports with at ${otherKernel}: build the first kernel, or name one in DODONA_OTHER_KERNEL; nothing was planted`);
    return 2;
  }
  const counts = { caught: 0, missed: 0, stale: 0, broken: 0, unfinished: 0, caught_provisionally: 0, caught_without_mismatch: 0 };
  let defects = [];
  let shard = null;
  let inventoryCount = 0;
  let finished = false;
  let baselineRejected = false;
  let cleanedUp = true;
  let copy = null;
  try {
    // A list that is missing or cannot be read leaves the run unfinished; nothing is copied or planted.
    let listed;
    try {
      listed = readDefects(path.join(source, 'defects.json'));
      inventoryCount = listed.length;
      if (only.some((arg) => arg === '--shard' || arg.startsWith('--shard='))) {
        const [index, count] = only.slice(1).map(Number);
        if (only.length !== 3 || only[0] !== '--shard' || !only.slice(1).every((arg) => /^\d+$/.test(arg))
            || !(0 <= index && index < count && count <= inventoryCount)) {
          throw new Error('expected --shard INDEX COUNT with 0 <= INDEX < COUNT <= the number of listed defects');
        }
        shard = { index, count };
      }
    } catch (err) {
      log(`UNFINISHED: the defect list could not be read: ${err && err.message ? err.message : err}; nothing was planted`);
      return summarise();
    }
    if (shard) {
      defects = listed.filter((_, position) => position % shard.count === shard.index);
    } else {
      defects = only.length === 0 ? listed : listed.filter((defect) => only.includes(defect.file));
    }
    // Made inside the cleanup's reach, so a copy that fails part of the way is removed too.
    copy = fs.mkdtempSync(path.join(tmp, 'kernel2-plant-'));
    copyTree(source, copy);
    const baseline = judgeCopy(copy, JUDGES, { spawn });
    if (baseline.outcome === 'unfinished') {
      log(`the unchanged copy could not be judged: ${baseline.name} ${baseline.why}; nothing was planted`);
    } else if (baseline.outcome === 'rejected') {
      log(`the unchanged copy is rejected by ${baseline.name}; nothing was planted`);
      baselineRejected = true;
      finished = true;
    } else {
      for (const defect of defects) {
        const file = path.join(copy, defect.file);
        const original = fs.readFileSync(file, 'utf8');
        const parts = original.split(defect.find);
        let verdict;
        if (parts.length !== 2) {
          verdict = 'STALE';
          counts.stale += 1;
        } else {
          try {
            fs.writeFileSync(file, parts.join(defect.replace));
            verdict = judgeDefect(copy, defect, counts, spawn);
          } finally {
            // The next defect, and the removal, must find the file as it was.
            fs.writeFileSync(file, original);
          }
        }
        log(`${verdict.padEnd(26)} ${defect.name}`);
      }
      finished = true;
    }
  } catch (err) {
    log(`UNFINISHED: the run stopped: ${err && err.message ? err.message : err}`);
  } finally {
    if (copy !== null) cleanedUp = removeCopy(copy, remove, log, pause);
  }
  return summarise();

  function summarise() {
    const all = finished && cleanedUp && !baselineRejected && counts.caught === defects.length && defects.length > 0;
    const report = { defects: defects.length, ...counts, all_caught: only.length === 0 && all, finished, cleaned_up: cleanedUp };
    if (shard) {
      Object.assign(report, { shard_index: shard.index, shard_count: shard.count, inventory_count: inventoryCount, shard_caught: all });
    }
    emitSummary(report);
    if (all) return 0;
    if (!finished || !cleanedUp || counts.unfinished > 0 || counts.caught_provisionally > 0) return 2;
    return 1;
  }
}

// The defect list: an object whose `defects` is a list of entries, each with a non-empty name, a relative file
// inside the copy, and the text to find and to put in its place. Anything else throws.
function readDefects(file) {
  const manifest = JSON.parse(fs.readFileSync(file, 'utf8'));
  const defects = manifest !== null && typeof manifest === 'object' ? manifest.defects : undefined;
  if (!Array.isArray(defects)) throw new Error(`${path.basename(file)} has no list of defects`);
  defects.forEach((defect, number) => {
    const fields = defect !== null && typeof defect === 'object' ? defect : {};
    const strings = ['name', 'file', 'find', 'replace'].every((key) => typeof fields[key] === 'string');
    const validWitness = !Object.hasOwn(fields, 'witness') || (typeof fields.witness === 'string' && fields.witness.trim() !== '');
    if (!strings || !validWitness || fields.name === '' || fields.find === '' || fields.file === '' || path.isAbsolute(fields.file)
        || fields.file.split(/[\\/]/).includes('..')) {
      throw new Error(`defect ${number} in ${path.basename(file)} is malformed`);
    }
  });
  return defects;
}

const REMOVE_ATTEMPTS = 3;
const WORKER_ARGUMENT = '--dodona-plant-worker';
const BATCH_MARKER = 'batch-owner.json';

function removeTree(directory) {
  fs.rmSync(directory, { recursive: true, force: true });
}

function recordBatchOwner(owned, worker = null) {
  const marker = path.join(owned, BATCH_MARKER);
  const pending = path.join(owned, 'batch-owner.next');
  const record = { schema: 1, batch: path.basename(owned), supervisor: process.pid, worker };
  fs.writeFileSync(pending, JSON.stringify(record), { encoding: 'utf8', mode: 0o600, flag: 'wx' });
  fs.renameSync(pending, marker);
}

function startBatchWorker(work, only) {
  return fork(__filename, [WORKER_ARGUMENT, work, ...only], {
    stdio: ['inherit', 'inherit', 'inherit', 'ipc'],
  });
}

function workerResult(worker) {
  return new Promise((resolve) => {
    let receipt;
    let received = 0;
    let error;
    worker.on('message', (message) => { receipt = message; received += 1; });
    worker.once('error', (failure) => { error = failure; });
    worker.once('close', (status, signal) => resolve({ status, signal, error, receipt, received }));
  });
}

async function runOwnedBatch(owned, only, startWorker) {
  const work = path.join(owned, 'work');
  const worker = startWorker(work, only);
  const result = workerResult(worker);
  if (!Number.isInteger(worker.pid)) return result;
  try {
    recordBatchOwner(owned, worker.pid);
    fs.mkdirSync(work, { mode: 0o700 });
    worker.send('start', (error) => {
      if (error) worker.kill();
    });
  } catch (error) {
    worker.kill();
    return { ...await result, error };
  }
  return result;
}

function receiptMatchesExit(receipt, status, only) {
  if (!receipt || receipt.status !== status || ![0, 1, 2].includes(status)) return false;
  const summary = receipt.summary;
  if (summary === null) return status === 2;
  if (!summary || !Number.isInteger(summary.defects) || !Number.isInteger(summary.caught)
      || ![summary.finished, summary.cleaned_up, summary.all_caught].every((value) => typeof value === 'boolean')) {
    return false;
  }
  if (status === 0) {
    const isShard = only[0] === '--shard';
    const expectedSummary = isShard
      ? summary.shard_caught === true && summary.shard_index === Number(only[1]) && summary.shard_count === Number(only[2])
      : summary.all_caught === (only.length === 0);
    return expectedSummary && summary.finished && summary.cleaned_up
      && summary.defects > 0 && summary.caught === summary.defects;
  }
  return !summary.all_caught && summary.shard_caught !== true;
}

async function supervise({
  only = process.argv.slice(2),
  tmp = os.tmpdir(),
  startWorker = startBatchWorker,
  log = console.log,
  remove = removeTree,
  pause = sleep,
} = {}) {
  let owned;
  let result;
  try {
    owned = fs.mkdtempSync(path.join(tmp, 'dodona-plant-batch-'));
    recordBatchOwner(owned);
    result = await runOwnedBatch(owned, only, startWorker);
  } catch (error) {
    result = { error };
  }
  if (owned && !removeCopy(owned, remove, log, pause)) return 2;
  if (result.error || result.signal || result.received !== 1
      || !receiptMatchesExit(result.receipt, result.status, only)) {
    const cause = result.error?.message || result.signal || `exit ${result.status}`;
    log(`UNFINISHED: the planted-defect worker produced no valid completion receipt (${cause})`);
    return 2;
  }
  if (result.receipt.summary !== null) log(JSON.stringify(result.receipt.summary));
  return result.status;
}

function runBatchWorker(tmp, only) {
  let summary = null;
  const status = main({ tmp, only, emitSummary: (report) => { summary = report; } });
  process.exitCode = status;
  process.send({ status, summary }, (error) => {
    if (error) process.exitCode = 2;
    if (process.connected) process.disconnect();
  });
}

// Removes this run's own copy, the exact directory it made and nothing else, trying a bounded number of times
// (a file a virus scanner or indexer holds open on Windows is let go soon after). True only once the directory
// is gone; a copy still there after the last attempt leaves the run unfinished.
function removeCopy(copy, remove, log, pause) {
  let last = null;
  for (let attempt = 1; attempt <= REMOVE_ATTEMPTS; attempt += 1) {
    try {
      remove(copy);
      if (!fs.existsSync(copy)) return true;
      last = new Error('the directory is still there');
    } catch (err) {
      last = err;
    }
    if (attempt < REMOVE_ATTEMPTS) pause(100 * attempt);
  }
  log(`UNFINISHED: the temporary copy ${copy} could not be removed after ${REMOVE_ATTEMPTS} attempts: ${last && last.message ? last.message : last}`);
  return false;
}

// The worker and the supervisor both use this bounded removal retry.
function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

module.exports = { JUDGES, REMOVE_ATTEMPTS, UNIT_TESTS, auxiliaryVerdict, judgeCopy, loads, main, readDefects, scenarioVerdict, supervise };

if (require.main === module) {
  const [mode, tmp, ...only] = process.argv.slice(2);
  if (mode === WORKER_ARGUMENT && typeof process.send === 'function') {
    process.exitCode = 2;
    process.once('message', (command) => {
      if (command === 'start') runBatchWorker(tmp, only);
      else if (process.connected) process.disconnect();
    });
  } else {
    supervise().then((status) => { process.exitCode = status; });
  }
}
