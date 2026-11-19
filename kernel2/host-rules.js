'use strict';
// The rules a schema cannot express, for one check (conformance/README.md, "Host
// checks"). Pure functions: each returns the reason the host's input, a manifest, a
// run description or a final is refused, or null. The rules are kept in the
// contract's order, and the first broken gives the reason.

const { checkPath } = require('./paths');
const { identityOf } = require('./identity');

const MAX_RUNS = 8;
const VERDICTS = ['passed', 'failed', 'error', 'unsupported'];
const RESTING_ON_A_RUN = ['passed', 'failed'];
const RANKS = ['documented', 'sampled', 'bounded', 'exhaustive'];
const TOOL_NAME = /^[A-Za-z0-9._-]+$/;

// `${tool:NAME}` wherever it stands in an argument: every tool an argument names.
const TOOL_REFERENCE = /\$\{tool:([^}]*)\}/g;
// An argument that starts with a tool and a file in it: `${tool:NAME}/PATH`.
const TOOL_FILE_START = /^\$\{tool:[^}]*\}\/(.*)$/s;
// Each segment of PATH in `${tool:NAME}/PATH` holds ASCII letters, digits, `.`, `_` and
// `-` only (rule 5), so nothing such as `=/etc/passwd` can be carried after a tool file.
const TOOL_FILE_SEGMENT = /^[A-Za-z0-9._-]+$/;
// An argument that is, whole, one file of a tool (rule 6).
const WHOLE_TOOL_FILE = /^\$\{tool:[^}]*\}\/[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*$/;
// Characters that can start or join a path; any of them makes an argument a path.
const PATH_CHARACTERS = ['/', '\\', '~', '@', '$', '%', '..'];

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isString(value) {
  return typeof value === 'string';
}

// A list whose every member is an object with these fields as strings.
function isListOf(value, fields) {
  return Array.isArray(value) && value.every((item) => isObject(item) && fields.every((field) => isString(item[field])));
}

// A list, or an empty one in its place. Used only after the shape has been checked,
// so that each later rule stands on its own.
function list(value) {
  return Array.isArray(value) ? value : [];
}

function objectOr(value) {
  return isObject(value) ? value : {};
}

function isArgv(value) {
  return Array.isArray(value) && value.length > 0 && value.every(isString);
}

// ASCII letters lowered, nothing else: how output and input paths are compared.
function asciiLower(text) {
  return text.replace(/[A-Z]/g, (letter) => String.fromCharCode(letter.charCodeAt(0) + 32));
}

function passesPathCheck(path) {
  return isString(path) && checkPath(Buffer.from(path, 'utf8')).accepted === true;
}

// The host's own input: `bad-input` unless it has the contract's shape.
function inputProblem(request) {
  if (!isObject(request)) return 'bad-input';
  if (!isString(request.root) || !isArgv(request.provider) || !isArgv(request.executor)) return 'bad-input';
  const obligation = request.obligation;
  if (!isObject(obligation) || !Array.isArray(obligation.specified_by) || !obligation.specified_by.every(isString)
    || !Array.isArray(obligation.targets) || !obligation.targets.every(isString)) return 'bad-input';
  if (!isListOf(request.inputs, ['path', 'identity'])) return 'bad-input';
  if (!isListOf(request.tools, ['name', 'digest'])) return 'bad-input';
  if (!isObject(request.platform)) return 'bad-input';
  if (!Number.isSafeInteger(request.deadline_ms) || request.deadline_ms <= 0) return 'bad-input';
  return null;
}

// The manifest of a checking provider: `bad-manifest` unless it has the contract's shape.
function manifestProblem(manifest) {
  if (!isObject(manifest) || !Array.isArray(manifest.capabilities)) return 'bad-manifest';
  if (!manifest.capabilities.every((entry) => isObject(entry) && isString(entry.capability))) return 'bad-manifest';
  const names = manifest.capabilities.map((entry) => entry.capability);
  if (new Set(names).size !== names.length) return 'bad-manifest';
  const check = manifest.capabilities.find((entry) => entry.capability === 'obligation.check');
  if (check !== undefined && 'strength' in check
    && !(isObject(check.strength) && isString(check.strength.class) && RANKS.includes(check.strength.rank))) return 'bad-manifest';
  if (!Array.isArray(manifest.tools) || !manifest.tools.every((tool) => isObject(tool) && isString(tool.name) && TOOL_NAME.test(tool.name))) return 'bad-manifest';
  return null;
}

// The strength the manifest declares for obligation.check, or null.
function ceilingOf(manifest) {
  const entry = manifest.capabilities.find((capability) => capability.capability === 'obligation.check');
  return entry !== undefined && isObject(entry.strength) ? entry.strength : null;
}

function declaredTools(manifest) {
  return new Set(manifest.tools.map((tool) => tool.name));
}

// Rule 2: the shape of a run description.
function hasShape(run) {
  return isObject(run)
    && isObject(run.program) && isString(run.program.tool) && isString(run.program.path)
    && Array.isArray(run.args)
    && isListOf(run.inputs, ['path', 'identity'])
    && isListOf(run.outputs, ['path'])
    && isListOf(run.tools, ['name', 'digest'])
    && isObject(run.platform)
    && (!('cwd' in run) || isString(run.cwd))
    && (!('limits' in run) || (isObject(run.limits) && Object.values(run.limits).every(Number.isSafeInteger)));
}

// Every tool the run names: its program's, and each `${tool:NAME}` in any argument.
function toolsNamed(run) {
  const named = [objectOr(run.program).tool];
  for (const argument of list(run.args).filter(isString)) {
    for (const match of argument.matchAll(TOOL_REFERENCE)) named.push(match[1]);
  }
  return named;
}

// The PATH of every `${tool:NAME}/PATH` argument. An argument holding NUL is left to rule 10.
function toolFiles(run) {
  const files = [];
  for (const argument of list(run.args).filter(isString)) {
    if (argument.includes('\u0000')) continue;
    const file = TOOL_FILE_START.exec(argument);
    if (file !== null) files.push(file[1]);
  }
  return files;
}

// Every path rule 5 checks: the program's, each input's and output's, each file a
// `${tool:NAME}/PATH` argument places, and the starting directory.
function pathsOf(run) {
  const paths = [objectOr(run.program).path, ...list(run.inputs).map((input) => objectOr(input).path),
    ...list(run.outputs).map((output) => objectOr(output).path), ...toolFiles(run)];
  if ('cwd' in run) paths.push(run.cwd);
  return paths;
}

function holdsToolFileCharacters(file) {
  return file.split('/').every((segment) => TOOL_FILE_SEGMENT.test(segment));
}

function isFreeWord(argument) {
  if (PATH_CHARACTERS.some((characters) => argument.includes(characters))) return false;
  for (let i = 0; i < argument.length; i += 1) {
    const code = argument.charCodeAt(i);
    if (code < 0x20 || code > 0x7e) return false;
  }
  return true;
}

// Rule 6: an argument that is not a free word is, whole, one of the run's input paths
// or one file of a tool. An argument that is not a string, or holds NUL, is left to rule 10.
function argumentAllowed(argument, inputs) {
  if (!isString(argument) || argument.includes('\u0000')) return true;
  return isFreeWord(argument) || inputs.includes(argument) || WHOLE_TOOL_FILE.test(argument);
}

// The check a run belongs to: what it was asked for and what it may use.
//   platform    the platform the check was asked for
//   declared    Set of tool names the manifest declares
//   given       Map of tool name to digest, the tools the check was given
//   inputs      Map of path to identity, the check's inputs
//   named       the files the obligation names (specified_by and targets)
//   runs        how many runs the check has had so far
function runProblem(description, check) {
  if (check.runs >= MAX_RUNS) return 'too-many-runs';
  if (!hasShape(description)) return 'bad-description';
  const run = objectOr(description);
  const args = list(run.args);
  const inputs = list(run.inputs).map(objectOr);
  const outputs = list(run.outputs).map(objectOr);
  const tools = list(run.tools).map(objectOr);
  if (identityOf(run.platform === undefined ? null : run.platform) !== identityOf(check.platform)) return 'platform-mismatch';
  if (toolsNamed(run).some((name) => !check.declared.has(name))) return 'undeclared-tool';
  if (toolsNamed(run).some((name) => !check.given.has(name))) return 'tool-not-in-key';
  if (tools.some((tool) => !check.given.has(tool.name))) return 'tool-not-in-key';
  if (tools.some((tool) => check.given.get(tool.name) !== tool.digest)) return 'tool-digest-mismatch';
  if (!pathsOf(run).every(passesPathCheck)) return 'bad-path';
  if (!toolFiles(run).every(holdsToolFileCharacters)) return 'bad-path';
  const runInputs = inputs.map((input) => input.path);
  if (!args.every((argument) => argumentAllowed(argument, runInputs))) return 'bad-path';
  if ('env' in run) return 'env-not-allowed';
  const taken = new Set([...runInputs, ...check.inputs.keys()].map(asciiLower));
  if (outputs.some((output) => taken.has(asciiLower(output.path)))) return 'output-overwrites-input';
  if (inputs.some((input) => !check.inputs.has(input.path))) return 'input-not-in-key';
  if (inputs.some((input) => check.inputs.get(input.path) !== input.identity)) return 'identity-mismatch';
  if (!args.every((argument) => isString(argument) && !argument.includes('\u0000'))) return 'bad-arguments';
  if (!check.named.every((path) => runInputs.includes(path))) return 'missing-input';
  return null;
}

function rank(strength) {
  return isObject(strength) ? RANKS.indexOf(strength.rank) : -1;
}

// The check a final belongs to:
//   runs           how many runs exited and were passed back
//   ceiling        the strength the manifest declares for obligation.check, or null
//   isRegularFile  path to true if it names, under the root and through no symbolic
//                  link, a regular file small enough to hash
//   identityOf     path to the identity of its bytes under the root, or null
function finalProblem(final, check) {
  if (!isObject(final)) return 'bad-final';
  if ('attachments' in final && !isListOf(final.attachments, ['path', 'identity'])) return 'bad-final';
  const attachments = list(final.attachments).map(objectOr);
  if (!attachments.every((attachment) => passesPathCheck(attachment.path))) return 'bad-path';
  if (!attachments.every((attachment) => check.isRegularFile(attachment.path))) return 'bad-path';
  if (!attachments.every((attachment) => check.identityOf(attachment.path) === attachment.identity)) return 'identity-mismatch';
  if (!VERDICTS.includes(final.verdict)) return 'bad-verdict';
  if (!RESTING_ON_A_RUN.includes(final.verdict)) return null;
  if (check.runs < 1) return 'verdict-without-run';
  if (rank(final.strength) < 0 || rank(final.strength) > rank(check.ceiling)) return 'strength-above-ceiling';
  if (objectOr(final.strength).class !== objectOr(check.ceiling).class) return 'strength-class-mismatch';
  return null;
}

module.exports = {
  inputProblem, manifestProblem, ceilingOf, declaredTools, runProblem, finalProblem, toolsNamed, argumentAllowed, MAX_RUNS, RANKS,
};
