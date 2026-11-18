'use strict';
// Checks that the judges can fail. Copies kernel2/ to a temporary directory,
// plants each defect from defects.json in the copy one at a time, and runs ALL
// the judges against it.
//
//     node kernel2/plant.js
//
// Per defect it prints
//   caught  the first judge that rejected the defective copy,
//   MISSED  every judge accepted it,
//   STALE   the text to replace was not found exactly once (nothing planted),
//   BROKEN  the defective copy does not even load, so nothing was learned.
// Then a JSON summary. Exit status 0 only if every defect was caught.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');

// Each judge: a name, the tool, and the arguments after `node <kernel>`.
const JUDGES = [
  { name: 'run_kit', tool: 'run_kit.py', args: ['scenario'] },
  { name: 'run_ledger_cases', tool: 'run_ledger_cases.py', args: [] },
  { name: 'run_key_vectors', tool: 'run_key_vectors.py', args: ['key'] },
  { name: 'run_attest_check', tool: 'run_attest_check.py', args: ['scenario'] },
  { name: 'run_vectors', tool: 'run_vectors.py', args: ['canonical'] },
  { name: 'run_path_vectors', tool: 'run_path_vectors.py', args: ['path', 'path-set'] },
];

// Does the copy load? Asks it to canonicalise `{}`; that loads every module.
function loads(copy) {
  const run = spawnSync('node', [path.join(copy, 'dodona-kernel2.js'), 'canonical'], { input: '{}', encoding: 'utf8' });
  return run.status === 0 && run.stdout.includes('"canonical":"{}"');
}

// The name of the first judge that rejects the copy, or null if all accept it.
function firstRejection(copy) {
  for (const judge of JUDGES) {
    const run = spawnSync('python3', [path.join('tools', judge.tool), '--', 'node', path.join(copy, 'dodona-kernel2.js'), ...judge.args], {
      cwd: root,
      encoding: 'utf8',
    });
    if (run.status !== 0) return judge.name;
  }
  return null;
}

function main() {
  const { defects } = JSON.parse(fs.readFileSync(path.join(__dirname, 'defects.json'), 'utf8'));
  const copy = fs.mkdtempSync(path.join(os.tmpdir(), 'kernel2-plant-'));
  fs.cpSync(__dirname, copy, { recursive: true });
  const counts = { caught: 0, missed: 0, stale: 0, broken: 0 };
  try {
    const baseline = firstRejection(copy);
    if (baseline !== null) {
      console.log(`the unchanged copy is rejected by ${baseline}; nothing was planted`);
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
          const judge = firstRejection(copy);
          verdict = judge === null ? 'MISSED' : `caught (${judge})`;
          if (judge === null) counts.missed += 1;
          else counts.caught += 1;
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
