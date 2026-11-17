#!/usr/bin/env node
'use strict';
// The second dodona kernel. Reads standard input, prints one JSON object.
//
//     node dodona-kernel2.js scenario | canonical | path | path-set | states
//
// This file is the only one that touches input and output.

const fs = require('node:fs');
const { runScenario } = require('./scenario');
const { judgeStates } = require('./states');
const { canonicalize } = require('./canonical');
const { checkPath, findCollisions } = require('./paths');

function decodeText(bytes) {
  try {
    return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch (error) {
    return null;
  }
}

function parseHex(text) {
  if (typeof text !== 'string' || text.length % 2 !== 0 || !/^[0-9a-fA-F]*$/.test(text)) {
    throw new Error('hex must be an even number of hexadecimal digits');
  }
  return Buffer.from(text, 'hex');
}

const commands = {
  scenario: (bytes) => runScenario(JSON.parse(bytes.toString('utf8'))),
  states: (bytes) => judgeStates(JSON.parse(bytes.toString('utf8'))),
  canonical: (bytes) => {
    const text = decodeText(bytes);
    return text === null ? { refused: 'not-json' } : canonicalize(text);
  },
  path: (bytes) => checkPath(parseHex(JSON.parse(bytes.toString('utf8')).hex)),
  'path-set': (bytes) => ({ collisions: findCollisions(JSON.parse(bytes.toString('utf8')).paths) }),
};

function main() {
  const command = commands[process.argv[2]];
  if (command === undefined) {
    process.stderr.write('usage: dodona-kernel2.js scenario | canonical | path | path-set | states\n');
    process.exitCode = 2;
    return;
  }
  try {
    const answer = command(fs.readFileSync(0));
    process.stdout.write(`${JSON.stringify(answer)}\n`);
  } catch (error) {
    process.stderr.write(`error: ${error.message}\n`);
    process.exitCode = 2;
  }
}

main();
