#!/usr/bin/env node
'use strict';
// The second dodona kernel. Reads standard input, prints one JSON object.
//
//     node dodona-kernel2.js scenario | canonical | key | path | path-set | states | ledger-append | ledger-read | check | status | run
//     node dodona-kernel2.js session --deadline-ms N --max-line N --max-log N -- <provider command>
//
// The rules are pure functions. This file reads the kernel's own input and output;
// session.js, check.js and the modules they use start and talk to the commands a
// host is given (a provider, an executor), and ledger-file.js keeps the ledger file.

const fs = require('node:fs');
const { runScenario } = require('./scenario');
const { judgeStates } = require('./states');
const { canonicalize } = require('./canonical');
const { checkPath, findCollisions } = require('./paths');
const { coreKey } = require('./identity');
const ledgerFile = require('./ledger-file');
const strictJson = require('./strict-json');
const { plain } = require('./plain');
const { runSession } = require('./session');
const { runCheck } = require('./check');
const { projectStatus } = require('./project-status');
const { projectRun } = require('./project-run');

function decodeText(bytes) {
  try {
    return new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch (error) {
    return null;
  }
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

// The check command's input, or null when it is not JSON at all: the check refuses
// that, as any input without its shape, with `bad-input`.
function readCheckInput(bytes) {
  try {
    return readInput(bytes);
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
  check: (bytes) => runCheck(readCheckInput(bytes)),
  // Reads its own input: whatever it is given, it answers with one object and exits 0.
  status: (bytes) => projectStatus(bytes),
  // As status: whatever it is given, it answers with one object and exits 0.
  run: (bytes) => projectRun(bytes),
};

// Commands that read no standard input, given the rest of the command line.
const noInput = {
  session: (argv) => runSession(argv),
};

const USAGE = 'usage: dodona-kernel2.js scenario | canonical | key | path | path-set | states | ledger-append | ledger-read | check | status | run\n'
  + '       dodona-kernel2.js session --deadline-ms N --max-line N --max-log N -- <provider command>\n';

// Prints the answer, then ends the process: a process a provider left behind and that
// was ended must not keep this one waiting on a stream it held.
function finish(answer, code) {
  const text = answer === undefined ? '' : `${JSON.stringify(answer)}\n`;
  process.stdout.write(text, () => process.exit(code));
}

function fail(error) {
  process.stderr.write(`error: ${error.message}\n`, () => process.exit(2));
}

function main() {
  const name = process.argv[2];
  if (noInput[name] !== undefined) {
    Promise.resolve().then(() => noInput[name](process.argv.slice(3))).then((answer) => finish(answer, 0), fail);
    return;
  }
  const command = commands[name];
  if (command === undefined) {
    process.stderr.write(USAGE);
    process.exitCode = 2;
    return;
  }
  let answer;
  try {
    answer = command(fs.readFileSync(0));
  } catch (error) {
    fail(error);
    return;
  }
  if (answer instanceof Promise) {
    answer.then((value) => finish(value, 0), fail);
    return;
  }
  process.stdout.write(`${JSON.stringify(answer)}\n`);
}

main();
