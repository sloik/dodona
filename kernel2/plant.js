'use strict';
// Checks that the judges can fail. Copies kernel2/ to a temporary directory,
// plants each defect from defects.json in the copy one at a time, and runs ALL
// the judges against it.
//
//     node kernel2/plant.js [FILE...]
//
// With FILE names (such as project-status.js), only the defects planted in those files
// are tried; the unchanged copy is still put to every judge first.
//
// Per defect it prints
//   caught  the first judge that rejected the defective copy (judges are tried one at a
//           time and the first rejection ends the defect's turn); a judge that exited
//           non-zero without reporting a mismatch is named as such, and counted apart,
//   MISSED  every judge accepted it, or only the unit tests (node --test) rejected it,
//   STALE   the text to replace was not found exactly once (nothing planted),
//   BROKEN  the defective copy does not even load, so nothing was learned.
// Then a JSON summary. Exit status 0 only if every defect was caught.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

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
// arguments after `node <kernel>`.
const JUDGES = [
  { name: 'run_kit', tool: 'run_kit.py', args: ['scenario'] },
  { name: 'run_ledger_cases', tool: 'run_ledger_cases.py', args: [] },
  { name: 'run_key_vectors', tool: 'run_key_vectors.py', args: ['key'] },
  { name: 'run_attest_check', tool: 'run_attest_check.py', args: ['scenario'] },
  { name: 'run_input_cases', tool: 'run_input_cases.py', args: [] },
  { name: 'run_harness_check', tool: 'run_harness_check.py', args: ['scenario'] },
  { name: 'run_vectors', tool: 'run_vectors.py', args: ['canonical'] },
  { name: 'run_path_vectors', tool: 'run_path_vectors.py', args: ['path', 'path-set'] },
  { name: 'run_provider_cases', tool: 'run_provider_cases.py', args: ['session'] },
  { name: 'run_check_cases', tool: 'run_check_cases.py', args: ['check'] },
  { name: 'run_status_cases', tool: 'run_status_cases.py', before: ['--jobs', STATUS_JOBS, '--kernel', OTHER_KERNEL], args: ['status'] },
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

// Does the copy load? Asks it to canonicalise `{}`; that loads every module.
function loads(copy) {
  const run = spawnSync('node', [path.join(copy, 'dodona-kernel2.js'), 'canonical'], { input: '{}', encoding: 'utf8' });
  return run.status === 0 && run.stdout.includes('"canonical":"{}"');
}

// The first judge that rejects the copy, as { name, mismatch }, or null if all accept it.
// `mismatch` is false when the judge exited non-zero without reporting a mismatch: it
// rejected the copy, but not by finding a case it answers wrongly.
function firstRejection(copy, judges = JUDGES) {
  for (const judge of judges) {
    const run = spawnSync(PYTHON, [path.join('tools', judge.tool), ...(judge.before || []), '--', 'node', path.join(copy, 'dodona-kernel2.js'), ...judge.args], {
      cwd: root,
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
    });
    if (run.status !== 0) return { name: judge.name, mismatch: run.status === 1 && /MISMATCH/.test(run.stdout || ''), status: run.status };
  }
  // Last: the unit tests of the copy, run against the repository's kit files. They are not a judge
  // of the kit, so a defect only they reject is reported as missed by the kit.
  const tests = spawnSync('node', ['--test', path.join(copy, 'test.js')], { env: { ...process.env, DODONA_ROOT: root }, encoding: 'utf8' });
  if (tests.status !== 0) return { name: UNIT_TESTS, mismatch: true, status: tests.status };
  return null;
}

function main() {
  if (!fs.existsSync(OTHER_KERNEL)) {
    console.log(`no kernel to recompute status reports with at ${OTHER_KERNEL}: build the first kernel, or name one in DODONA_OTHER_KERNEL; nothing was planted`);
    process.exitCode = 2;
    return;
  }
  const only = process.argv.slice(2);
  const { defects: listed } = JSON.parse(fs.readFileSync(path.join(__dirname, 'defects.json'), 'utf8'));
  const defects = only.length === 0 ? listed : listed.filter((defect) => only.includes(defect.file));
  const copy = fs.mkdtempSync(path.join(os.tmpdir(), 'kernel2-plant-'));
  fs.cpSync(__dirname, copy, { recursive: true });
  const counts = { caught: 0, missed: 0, stale: 0, broken: 0, caught_without_mismatch: 0 };
  try {
    const baseline = firstRejection(copy);
    if (baseline !== null) {
      console.log(`the unchanged copy is rejected by ${baseline.name}; nothing was planted`);
      console.log(JSON.stringify({ defects: defects.length, caught: 0, all_caught: false }));
      process.exitCode = 1;
      return;
    }
    for (const defect of defects) {
      const file = path.join(copy, defect.file);
      const original = fs.readFileSync(file, 'utf8');
      const parts = original.split(defect.find);
      let verdict;
      if (parts.length !== 2) {
        verdict = 'STALE';
        counts.stale += 1;
      } else {
        fs.writeFileSync(file, parts.join(defect.replace));
        if (!loads(copy)) {
          verdict = 'BROKEN';
          counts.broken += 1;
        } else {
          const judge = firstRejection(copy, judgesFor(defect.file));
          if (judge === null) verdict = 'MISSED';
          else if (judge.name === UNIT_TESTS) verdict = 'MISSED by the kit (only node --test rejects it)';
          else if (judge.mismatch) verdict = `caught (${judge.name})`;
          else verdict = `caught (${judge.name} exited ${judge.status} without a mismatch)`;
          if (judge === null || judge.name === UNIT_TESTS) counts.missed += 1;
          else counts.caught += 1;
          if (judge !== null && judge.name !== UNIT_TESTS && !judge.mismatch) counts.caught_without_mismatch += 1;
        }
        fs.writeFileSync(file, original);
      }
      console.log(`${verdict.padEnd(26)} ${defect.name}`);
    }
  } finally {
    fs.rmSync(copy, { recursive: true, force: true });
  }
  const all = counts.caught === defects.length && defects.length > 0;
  console.log(JSON.stringify({ defects: defects.length, ...counts, all_caught: all }));
  process.exitCode = all ? 0 : 1;
}

main();
