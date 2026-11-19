'use strict';
// The rules a schema cannot express, for one check (conformance/README.md, "Host
// checks"). Pure functions: each returns the reason a run description or a final is
// refused, or null. The rules are kept in the contract's order, and the first broken
// gives the reason.

const { checkPath } = require('./paths');
const { identityOf } = require('./identity');

const MAX_RUNS = 8;
const VERDICTS = ['passed', 'failed', 'error', 'unsupported'];
const RESTING_ON_A_RUN = ['passed', 'failed'];
const RANKS = ['documented', 'sampled', 'bounded', 'exhaustive'];

// `${tool:NAME}` wherever it stands in an argument: every tool an argument names.
const TOOL_REFERENCE = /\$\{tool:([^}]*)\}/g;
// An argument that starts with a tool and a file in it: `${tool:NAME}/PATH`.
const TOOL_FILE_START = /^\$\{tool:[^}]*\}\/(.*)$/s;
// An argument that is, whole, one file of a tool. The contract does not say which
// characters PATH may hold beyond the path check; taken narrowly, each of its segments
// holds letters, digits, `.`, `_` and `-` only, so nothing such as `=/etc/passwd` can
// be appended to a tool file (check-cases.json, `tool-file-with-a-tail`).
const WHOLE_TOOL_FILE = /^\$\{tool:[^}]*\}\/[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*$/;
// Characters that can start or join a path; any of them makes an argument a path.
const PATH_CHARACTERS = ['/', '\\', '~', '@', '$', '%', '..'];

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function same(a, b) {
  return a !== undefined && b !== undefined && identityOf(a) === identityOf(b);
}

function passesPathCheck(path) {
  return typeof path === 'string' && checkPath(Buffer.from(path, 'utf8')).accepted === true;
}

// The string arguments of a run, or none if `args` is not a list (rule 9 says so).
function stringArguments(run) {
  return list(run.args).filter((argument) => typeof argument === 'string');
}

// Every tool the run names: its program's, and each `${tool:NAME}` in any argument.
function toolsNamed(run) {
  const program = isObject(run.program) ? run.program : {};
  const named = [program.tool];
  for (const argument of stringArguments(run)) {
    for (const match of argument.matchAll(TOOL_REFERENCE)) named.push(match[1]);
  }
  return named;
}

function inputPaths(run) {
  return list(run.inputs).map((input) => (isObject(input) ? input.path : undefined));
}

function outputPaths(run) {
  return list(run.outputs).map((output) => (isObject(output) ? output.path : undefined));
}

// Every path rule 4 checks: the program's, each input's and output's, each file a
// `${tool:NAME}/PATH` argument places, and the starting directory.
function pathsOf(run) {
  const program = isObject(run.program) ? run.program : {};
  const paths = [program.path, ...inputPaths(run), ...outputPaths(run)];
  for (const argument of stringArguments(run)) {
    const file = TOOL_FILE_START.exec(argument);
    if (file !== null) paths.push(file[1]);
  }
  if (run.cwd !== undefined) paths.push(run.cwd);
  return paths;
}

function isFreeWord(argument) {
  if (PATH_CHARACTERS.some((characters) => argument.includes(characters))) return false;
  for (let i = 0; i < argument.length; i += 1) {
    const code = argument.charCodeAt(i);
    if (code < 0x20 || code > 0x7e) return false;
  }
  return true;
}

// Rule 5: an argument that is not a free word is, whole, one of the run's input paths
// or one file of a tool. An argument holding NUL is left to rule 9.
function argumentAllowed(argument, inputs) {
  if (argument.includes('\u0000')) return true;
  return isFreeWord(argument) || inputs.includes(argument) || WHOLE_TOOL_FILE.test(argument);
}

function setsNoEnvironment(run) {
  return run.env === undefined || (isObject(run.env) && Object.keys(run.env).length === 0);
}

// The check a run belongs to: what it was asked for and what it may use.
//   platform    the platform the check was asked for
//   declared    Set of tool names the manifest declares
//   given       Map of tool name to digest, the tools the check was given
//   inputs      Map of path to identity, the check's inputs
//   named       the files the obligation names (specified_by and targets)
//   runs        how many runs the check has had so far
function runProblem(description, check) {
  const run = isObject(description) ? description : {};
  if (check.runs >= MAX_RUNS) return 'too-many-runs';
  if (!same(run.platform, check.platform)) return 'platform-mismatch';
  if (toolsNamed(run).some((name) => !check.declared.has(name))) return 'undeclared-tool';
  if (toolsNamed(run).some((name) => !check.given.has(name))) return 'tool-not-in-key';
  if (list(run.tools).some((tool) => !isObject(tool) || !check.given.has(tool.name))) return 'tool-not-in-key';
  if (list(run.tools).some((tool) => check.given.get(tool.name) !== tool.digest)) return 'tool-digest-mismatch';
  if (!pathsOf(run).every(passesPathCheck)) return 'bad-path';
  if (!stringArguments(run).every((argument) => argumentAllowed(argument, inputPaths(run)))) return 'bad-path';
  if (!setsNoEnvironment(run)) return 'env-not-allowed';
  if (outputPaths(run).some((path) => inputPaths(run).includes(path))) return 'output-overwrites-input';
  if (list(run.inputs).some((input) => !check.inputs.has(input.path))) return 'input-not-in-key';
  if (list(run.inputs).some((input) => check.inputs.get(input.path) !== input.identity)) return 'identity-mismatch';
  if (!Array.isArray(run.args) || !run.args.every((argument) => typeof argument === 'string' && !argument.includes('\u0000'))) return 'bad-arguments';
  if (!check.named.every((path) => inputPaths(run).includes(path))) return 'missing-input';
  return null;
}

function rank(strength) {
  return isObject(strength) ? RANKS.indexOf(strength.rank) : -1;
}

// The check a final belongs to:
//   runs        how many runs exited and were passed back
//   ceiling     the strength the manifest declares for obligation.check, or null
//   identityOf  path to the identity of its bytes under the root, or null if unreadable
function finalProblem(answer, check) {
  const final = isObject(answer) ? answer : {};
  const attachments = list(final.attachments).map((attachment) => (isObject(attachment) ? attachment : {}));
  if (!attachments.every((attachment) => passesPathCheck(attachment.path))) return 'bad-path';
  if (!attachments.every((attachment) => check.identityOf(attachment.path) === attachment.identity)) return 'identity-mismatch';
  if (!VERDICTS.includes(final.verdict)) return 'bad-verdict';
  if (!RESTING_ON_A_RUN.includes(final.verdict)) return null;
  if (check.runs < 1) return 'verdict-without-run';
  if (rank(final.strength) < 0 || rank(final.strength) > rank(check.ceiling)) return 'strength-above-ceiling';
  if (final.strength.class !== check.ceiling.class) return 'strength-class-mismatch';
  return null;
}

module.exports = { runProblem, finalProblem, toolsNamed, argumentAllowed, MAX_RUNS, RANKS };
