'use strict';
// Runs every line of NormalizationTest.txt through our NFC and NFD and checks
// the invariants stated at the top of that file.
//
//     node kernel2/test-normalization.js <directory holding NormalizationTest.txt>

const fs = require('node:fs');
const path = require('node:path');
const unicode = require('./unicode');

function same(a, b) {
  return a.length === b.length && a.every((code, position) => code === b[position]);
}

function main() {
  const directory = process.argv[2];
  if (!directory) {
    process.stderr.write('usage: node test-normalization.js <data directory>\n');
    process.exit(2);
  }
  const text = fs.readFileSync(path.join(directory, 'NormalizationTest.txt'), 'utf8');
  let lines = 0;
  let failures = 0;
  const listed = new Set(); // single code points listed in Part 1
  let part = '';
  const fail = (lineNumber, what) => {
    failures += 1;
    if (failures <= 10) console.log(`FAIL line ${lineNumber}: ${what}`);
  };
  text.split('\n').forEach((raw, index) => {
    if (raw.startsWith('@Part')) part = raw.slice(5, 6);
    const line = raw.replace(/#.*/, '').trim();
    if (line === '' || line.startsWith('@')) return;
    const columns = line.split(';').slice(0, 5).map((column) => column.trim().split(/\s+/).map((h) => parseInt(h, 16)));
    const [c1, c2, c3, c4, c5] = columns;
    lines += 1;
    if (part === '1' && c1.length === 1) listed.add(c1[0]);
    const n = index + 1;
    // NFC: c2 == toNFC(c1) == toNFC(c2) == toNFC(c3); c4 == toNFC(c4) == toNFC(c5)
    for (const [label, input] of [['c1', c1], ['c2', c2], ['c3', c3]]) {
      if (!same(unicode.nfc(input), c2)) fail(n, `NFC(${label}) is not c2`);
    }
    for (const [label, input] of [['c4', c4], ['c5', c5]]) {
      if (!same(unicode.nfc(input), c4)) fail(n, `NFC(${label}) is not c4`);
    }
    // NFD: c3 == toNFD(c1) == toNFD(c2) == toNFD(c3); c5 == toNFD(c4) == toNFD(c5)
    for (const [label, input] of [['c1', c1], ['c2', c2], ['c3', c3]]) {
      if (!same(unicode.nfd(input), c3)) fail(n, `NFD(${label}) is not c3`);
    }
    for (const [label, input] of [['c4', c4], ['c5', c5]]) {
      if (!same(unicode.nfd(input), c5)) fail(n, `NFD(${label}) is not c5`);
    }
  });
  // Every assigned code point not listed in Part 1 is unchanged by NFC and NFD.
  let others = 0;
  for (let code = 0; code <= 0x10ffff; code += 1) {
    if (code >= 0xd800 && code <= 0xdfff) continue;
    if (!unicode.isAssigned(code) || listed.has(code)) continue;
    others += 1;
    if (!same(unicode.nfc([code]), [code]) || !same(unicode.nfd([code]), [code])) fail(0, `U+${code.toString(16)} changes`);
  }
  console.log(JSON.stringify({ lines, others, failures, all_passed: failures === 0 && lines > 0 }));
  process.exit(failures === 0 && lines > 0 ? 0 : 1);
}

main();
