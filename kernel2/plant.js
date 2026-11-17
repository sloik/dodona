'use strict';
// Checks that the conformance kit can fail. Copies kernel2/ to a temporary
// directory, plants each defect from defects.json in the copy one at a time,
// and runs the kit against it.
//
//     node kernel2/plant.js
//
// Prints `caught` (the kit rejected the defective copy), `MISSED` (the kit
// accepted it) or `STALE` (the text to replace was not found exactly once, so
// nothing was planted) per defect, then a JSON summary. Exit status 0 only if
// every defect was caught.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');

function kitPasses(copy) {
  const run = spawnSync('python3', ['tools/run_kit.py', '--', 'node', path.join(copy, 'dodona-kernel2.js'), 'scenario'], {
    cwd: root,
    encoding: 'utf8',
  });
  return run.status === 0;
}

function main() {
  const { defects } = JSON.parse(fs.readFileSync(path.join(__dirname, 'defects.json'), 'utf8'));
  const copy = fs.mkdtempSync(path.join(os.tmpdir(), 'kernel2-plant-'));
  fs.cpSync(__dirname, copy, { recursive: true });
  let caught = 0;
  try {
    if (!kitPasses(copy)) {
      console.log('the unchanged copy does not pass the kit; nothing was planted');
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
      } else {
        fs.writeFileSync(file, parts.join(defect.replace));
        verdict = kitPasses(copy) ? 'MISSED' : 'caught';
        fs.writeFileSync(file, original);
      }
      if (verdict === 'caught') caught += 1;
      console.log(`${verdict.padEnd(7)} ${defect.name}`);
    }
  } finally {
    fs.rmSync(copy, { recursive: true, force: true });
  }
  const all = caught === defects.length && defects.length > 0;
  console.log(JSON.stringify({ defects: defects.length, caught, all_caught: all }));
  process.exitCode = all ? 0 : 1;
}

main();
