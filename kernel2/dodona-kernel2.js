#!/usr/bin/env node
'use strict';
// The second dodona kernel. Reads standard input, prints one JSON object.
//
//     node dodona-kernel2.js scenario | canonical | key | path | path-set | states | ledger-append | ledger-read
//
// This file is the only one that touches input and output.

const fs = require('node:fs');
const { runScenario } = require('./scenario');
const { judgeStates } = require('./states');
const { canonicalize } = require('./canonical');
const { checkPath, findCollisions } = require('./paths');
const { coreKey } = require('./identity');
const ledgerFile = require('./ledger-file');
const strictJson = require('./strict-json');

function decodeText(bytes) {
  try {
    return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch (error) {
    return null;
  }
}

// Turns what the strict reader returns (Map, BigInt) into plain JavaScript values.
function plain(value) {
  if (value instanceof Map) {
    const object = {};
    for (const [key, member] of value) Object.defineProperty(object, key, { value: plain(member), enumerable: true, writable: true, configurable: true });
    return object;
  }
  if (Array.isArray(value)) return value.map(plain);
  if (typeof value === 'bigint') return Number(value);
  return value;
}

// Reads an input as strictly as the canonical encoding writes: bytes that are not
// UTF-8, a repeated key, or a number that is not an integer make the whole input
// refused, and the command stops with a status other than 0.
function readInput(bytes) {
  const text = decodeText(bytes);
  if (text === null) throw new Error('input is not UTF-8');
  const read = strictJson.read(text);
  if (read.refused !== undefined) throw new Error(`input refused: ${read.refused}`);
  return plain(read.value);
}

function parseHex(text) {
  if (typeof text !== 'string' || text.length % 2 !== 0 || !/^[0-9a-fA-F]*$/.test(text)) {
    throw new Error('hex must be an even number of hexadecimal digits');
  }
  return Buffer.from(text, 'hex');
}

const commands = {
  scenario: (bytes) => runScenario(readInput(bytes)),
  states: (bytes) => judgeStates(readInput(bytes)),
  canonical: (bytes) => {
    const text = decodeText(bytes);
    return text === null ? { refused: 'not-json' } : canonicalize(text);
  },
  path: (bytes) => checkPath(parseHex(readInput(bytes).hex)),
  key: (bytes) => {
    const text = decodeText(bytes);
    return text === null ? { refused: 'not-json' } : coreKey(text);
  },
  'ledger-append': (bytes) => ledgerFile.append(readInput(bytes)),
  'ledger-read': (bytes) => ledgerFile.read(readInput(bytes)),
  'path-set': (bytes) => ({ collisions: findCollisions(readInput(bytes).paths) }),
};

function main() {
  const command = commands[process.argv[2]];
  if (command === undefined) {
    process.stderr.write('usage: dodona-kernel2.js scenario | canonical | key | path | path-set | states | ledger-append | ledger-read\n');
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
