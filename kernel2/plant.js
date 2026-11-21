'use strict';
// Checks that the judges can fail. Copies kernel2/ to a temporary directory,
// plants each defect from defects.json in the copy one at a time, and runs ALL
// the judges against it.
//
//     node kernel2/plant.js [FILE...]
//     node kernel2/plant.js --shard INDEX/5
//
// With FILE names (such as project-status.js), only the defects planted in those files
// are tried; the unchanged copy is still put to every judge first.
// A fixed shard takes every fifth defect from INDEX in the pinned manifest. It reports
// shard_passed for that subset and always leaves the whole-suite all_caught flag false.
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
// The copy is removed when the run ends, and only this run's copy, with a bounded number of
// attempts; a copy still there after the last leaves the run unfinished. A run killed outright
// (SIGKILL, or a signal Node does not catch) can leave its copy behind; the summary then is never
// printed, so nothing claims it was removed.

const { createHash } = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
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

const SHARD_COUNT = 5;
const SHARD_INVENTORY_COUNT = 319;
const SHARD_MANIFEST_SHA256 = 'f06ffd803d8000ed3821f0b8533f9966ed92fa7af255a5020557637277d71e00';

function shardSelector(args) {
  if (!args.some((arg) => arg === '--shard' || (typeof arg === 'string' && arg.startsWith('--shard=')))) return null;
  const match = args.length === 2 && args[0] === '--shard' && /^([1-5])\/5$/.exec(args[1]);
  return match ? { index: Number(match[1]), count: SHARD_COUNT } : false;
}

function readShardInventory(file, expectedSha256) {
  const raw = fs.readFileSync(file);
  const sha256 = createHash('sha256').update(raw).digest('hex');
  if (sha256 !== expectedSha256) throw new Error('raw manifest SHA-256 differs from the fixed shard inventory');
  const defects = readDefects(file, raw.toString('utf8'));
  const count = defects.length;
  if (count !== SHARD_INVENTORY_COUNT || new Set(defects.map(({ name }) => name)).size !== count) {
    throw new Error('the fixed shard inventory must contain 319 distinct defect names');
  }
  return { defects, identity: { sha256, count } };
}

// Runs the batch and returns the exit status. Every argument is for tests; the defaults are the real run.
function main({
  spawn = spawnSync,
  source = __dirname,
  tmp = os.tmpdir(),
  only = process.argv.slice(2),
  shardManifestSha256 = SHARD_MANIFEST_SHA256,
  otherKernel = OTHER_KERNEL,
  log = console.log,
  copyTree = (from, to) => fs.cpSync(from, to, { recursive: true }),
  remove = (dir) => fs.rmSync(dir, { recursive: true, force: true }),
  pause = sleep,
} = {}) {
  const shard = shardSelector(only);
  if (shard === false) {
    log('UNFINISHED: use --shard INDEX/5 alone, with INDEX from 1 to 5');
    return 2;
  }
  if (!fs.existsSync(otherKernel)) {
    log(`no kernel to recompute status reports with at ${otherKernel}: build the first kernel, or name one in DODONA_OTHER_KERNEL; nothing was planted`);
    return 2;
  }
  const counts = { caught: 0, missed: 0, stale: 0, broken: 0, unfinished: 0, caught_provisionally: 0, caught_without_mismatch: 0 };
  let defects = [];
  let inventory = null;
  const covered = [];
  let finished = false;
  let baselinePassed = false;
  let baselineRejected = false;
  let cleanedUp = true;
  let copy = null;
  try {
    // A list that is missing or cannot be read leaves the run unfinished; nothing is copied or planted.
    try {
      const file = path.join(source, 'defects.json');
      if (shard) {
        const pinned = readShardInventory(file, shardManifestSha256);
        inventory = pinned.identity;
        defects = pinned.defects.filter((_, offset) => offset % shard.count === shard.index - 1);
      } else {
        const listed = readDefects(file);
        defects = only.length === 0 ? listed : listed.filter((defect) => only.includes(defect.file));
      }
    } catch (err) {
      log(`UNFINISHED: the defect list could not be read: ${err && err.message ? err.message : err}; nothing was planted`);
      return summarise();
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
      baselinePassed = true;
      for (const [offset, defect] of defects.entries()) {
        const caught = counts.caught;
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
        if (shard && counts.caught > caught) {
          covered.push({ index: shard.index + offset * shard.count, name: defect.name });
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
    const receipt = { defects: defects.length, ...counts, all_caught: !shard && all, finished, cleaned_up: cleanedUp };
    const shardPassed = all && baselinePassed && covered.length === defects.length;
    if (shard) {
      Object.assign(receipt, { shard, inventory, covered, baseline_passed: baselinePassed, shard_passed: shardPassed });
    }
    log(JSON.stringify(receipt));
    if (shard ? shardPassed : all) return 0;
    if (!finished || !cleanedUp || counts.unfinished > 0 || counts.caught_provisionally > 0) return 2;
    return 1;
  }
}

// The defect list: an object whose `defects` is a list of entries, each with a non-empty name, a relative file
// inside the copy, and the text to find and to put in its place. Anything else throws.
function readDefects(file, text = fs.readFileSync(file, 'utf8')) {
  const manifest = JSON.parse(text);
  const defects = manifest !== null && typeof manifest === 'object' ? manifest.defects : undefined;
  if (!Array.isArray(defects)) throw new Error(`${path.basename(file)} has no list of defects`);
  defects.forEach((defect, number) => {
    const fields = defect !== null && typeof defect === 'object' ? defect : {};
    const strings = ['name', 'file', 'find', 'replace'].every((key) => typeof fields[key] === 'string');
    if (!strings || fields.name === '' || fields.find === '' || fields.file === '' || path.isAbsolute(fields.file)
        || fields.file.split(/[\\/]/).includes('..')) {
      throw new Error(`defect ${number} in ${path.basename(file)} is malformed`);
    }
  });
  return defects;
}

const REMOVE_ATTEMPTS = 3;

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

// Waits without a busy loop; the runner is synchronous throughout.
function sleep(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

module.exports = { JUDGES, REMOVE_ATTEMPTS, UNIT_TESTS, auxiliaryVerdict, judgeCopy, loads, main, readDefects, scenarioVerdict };

if (require.main === module) process.exitCode = main();
