'use strict';
// Writes unicode-tables.js from the Unicode Character Database files.
//
//     node kernel2/gen-unicode-tables.js <directory holding the data files>
//
// Needed in that directory: UnicodeData.txt, CompositionExclusions.txt,
// CaseFolding.txt, DerivedNormalizationProps.txt. Only Node built-ins are used.

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const SOURCES = ['UnicodeData.txt', 'CompositionExclusions.txt', 'CaseFolding.txt', 'DerivedNormalizationProps.txt'];

function hex(text) {
  return parseInt(text, 16);
}

function hexList(text) {
  return text.trim().split(/\s+/).map(hex);
}

// The lines of a data file with comments and blank lines removed.
function dataLines(text) {
  const lines = [];
  for (const raw of text.split('\n')) {
    const line = raw.replace(/#.*/, '').trim();
    if (line !== '') lines.push(line);
  }
  return lines;
}

// Reads UnicodeData.txt: assigned ranges, combining classes, canonical decompositions.
function readUnicodeData(text) {
  const assigned = [];
  const classes = new Map();
  const decompositions = new Map();
  let rangeStart = null;
  for (const line of dataLines(text)) {
    const fields = line.split(';');
    const code = hex(fields[0]);
    const name = fields[1];
    if (name.endsWith(', First>')) {
      rangeStart = code;
      continue;
    }
    if (name.endsWith(', Last>')) {
      assigned.push([rangeStart, code]);
      rangeStart = null;
      continue;
    }
    assigned.push([code, code]);
    const combining = Number(fields[3]);
    if (combining !== 0) classes.set(code, combining);
    const mapping = fields[5];
    // A mapping that starts with a <tag> is a compatibility mapping and is not wanted.
    if (mapping !== '' && !mapping.startsWith('<')) decompositions.set(code, hexList(mapping));
  }
  return { assigned: mergeRanges(assigned), classes, decompositions };
}

function mergeRanges(ranges) {
  const merged = [];
  for (const [start, end] of ranges) {
    const last = merged[merged.length - 1];
    if (last && last[1] + 1 === start) last[1] = end;
    else merged.push([start, end]);
  }
  return merged;
}

// Combining classes as runs [first, last, class] of consecutive code points.
function classRuns(classes) {
  const runs = [];
  for (const code of [...classes.keys()].sort((a, b) => a - b)) {
    const value = classes.get(code);
    const last = runs[runs.length - 1];
    if (last && last[1] + 1 === code && last[2] === value) last[1] = code;
    else runs.push([code, code, value]);
  }
  return runs;
}

// Code points listed in CompositionExclusions.txt (a line is one code point).
function readExclusions(text) {
  return new Set(dataLines(text).map((line) => hex(line.split(/\s+/)[0])));
}

// Code points with the property Full_Composition_Exclusion in DerivedNormalizationProps.txt.
function readFullExclusion(text) {
  const found = new Set();
  for (const line of dataLines(text)) {
    const [range, property] = line.split(';').map((part) => part.trim());
    if (property !== 'Full_Composition_Exclusion') continue;
    const [first, last] = range.split('..');
    for (let code = hex(first); code <= hex(last === undefined ? first : last); code += 1) found.add(code);
  }
  return found;
}

// Full case folding: the lines marked C (common) and F (full) in CaseFolding.txt.
function readFoldings(text) {
  const foldings = [];
  for (const line of dataLines(text)) {
    const fields = line.split(';').map((part) => part.trim());
    if (fields[1] === 'C' || fields[1] === 'F') foldings.push([hex(fields[0]), hexList(fields[2])]);
  }
  return foldings.sort((a, b) => a[0] - b[0]);
}

// The pairs that compose, worked out from the rules and checked against the
// published Full_Composition_Exclusion list.
function composablePairs(data, exclusions, published) {
  const excluded = new Set(exclusions);
  for (const [code, mapping] of data.decompositions) {
    if (mapping.length === 1) excluded.add(code);
    else if (data.classes.has(code) || data.classes.has(mapping[0])) excluded.add(code);
  }
  const mine = [...excluded].sort((a, b) => a - b).join(',');
  const theirs = [...published].sort((a, b) => a - b).join(',');
  if (mine !== theirs) throw new Error('derived composition exclusions differ from Full_Composition_Exclusion');
  const pairs = [];
  for (const [code, mapping] of data.decompositions) {
    if (mapping.length === 2 && !excluded.has(code)) pairs.push([mapping[0], mapping[1], code]);
  }
  return pairs.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
}

function format(name, rows) {
  return `  ${name}: [\n${rows.map((row) => `    ${JSON.stringify(row)},`).join('\n')}\n  ],\n`;
}

function main() {
  const directory = process.argv[2];
  if (!directory) {
    process.stderr.write('usage: node gen-unicode-tables.js <data directory>\n');
    process.exit(2);
  }
  const texts = {};
  const header = [];
  for (const file of SOURCES) {
    const bytes = fs.readFileSync(path.join(directory, file));
    texts[file] = bytes.toString('utf8');
    header.push(`//   ${file}  sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`);
  }
  const version = /^# DerivedNormalizationProps-(\d+\.\d+\.\d+)\.txt/m.exec(texts['DerivedNormalizationProps.txt']);
  const data = readUnicodeData(texts['UnicodeData.txt']);
  const pairs = composablePairs(data, readExclusions(texts['CompositionExclusions.txt']),
    readFullExclusion(texts['DerivedNormalizationProps.txt']));
  const decompositions = [...data.decompositions].sort((a, b) => a[0] - b[0]);
  const out = [
    "'use strict';",
    '// Generated by gen-unicode-tables.js. Do not edit by hand.',
    `// Unicode version: ${version ? version[1] : 'unknown'}`,
    '// Source files:',
    ...header,
    '',
    'module.exports = {',
    `  version: ${JSON.stringify(version ? version[1] : 'unknown')},`,
    '  // Assigned code points as [first, last] ranges.',
    format('assigned', data.assigned),
    '  // Combining classes other than 0, as [first, last, class] runs.',
    format('combiningClasses', classRuns(data.classes)),
    '  // Canonical decompositions, one step: [code point, [code points]].',
    format('decompositions', decompositions),
    '  // Pairs that compose: [first, second, composite].',
    format('compositions', pairs),
    '  // Full case folding (statuses C and F): [code point, [code points]].',
    format('foldings', readFoldings(texts['CaseFolding.txt'])),
    '};',
    '',
  ];
  fs.writeFileSync(path.join(__dirname, 'unicode-tables.js'), out.join('\n'));
}

main();
