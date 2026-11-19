'use strict';
// One check taken from a provider to a verdict (conformance/README.md, "Host checks").
//
// In:  {"root", "provider": [argv], "obligation", "inputs", "tools", "platform", "executor": [argv], "deadline_ms"}
// Out: {"outcome": "verdict", "verdict": V} or {"outcome": "refused", "reason": R}
//
// The provider and the executor are commands the kernel is given; it names neither.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const processes = require('./processes');
const strictJson = require('./strict-json');
const { plain } = require('./plain');
const { identityOf } = require('./identity');
const { Wire, isObject } = require('./wire');
const { runProblem, finalProblem } = require('./host-rules');
const { ECHO } = require('./session');

const PROTOCOL = '0.2';
const MAX_LINE_BYTES = 1048576;
const MAX_LOG_BYTES = 1048576;
const MAX_REPORT_BYTES = 16 * 1048576;
// How long the host waits for the executor beyond the run's own wall limit, and in
// all when the run states none. A run it stops waiting for ends as timed-out.
const EXECUTOR_GRACE_MS = 60000;
const EXECUTOR_DEFAULT_MS = 600000;

function list(value) {
  return Array.isArray(value) ? value : [];
}

function refused(reason) {
  return { outcome: 'refused', reason };
}

function verdict(value) {
  return { outcome: 'verdict', verdict: value };
}

function isArgv(value) {
  return Array.isArray(value) && value.length > 0 && value.every((item) => typeof item === 'string');
}

function validRequest(request) {
  return isObject(request) && typeof request.root === 'string' && isArgv(request.provider) && isArgv(request.executor)
    && isObject(request.obligation) && Array.isArray(request.inputs) && Array.isArray(request.tools)
    && isObject(request.platform) && Number.isInteger(request.deadline_ms) && request.deadline_ms > 0;
}

// The files the obligation names.
function namedFiles(obligation) {
  return [...list(obligation.specified_by), ...list(obligation.targets)];
}

// The identity of a file's bytes under the root, or null if it cannot be read.
function fileIdentity(root, relative) {
  try {
    const bytes = fs.readFileSync(path.join(root, relative));
    return `sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`;
  } catch (error) {
    return null;
  }
}

// The strength the manifest declares for obligation.check, or null.
function ceilingOf(manifest) {
  const entry = list(manifest.capabilities).find((capability) => isObject(capability) && capability.capability === 'obligation.check');
  return entry !== undefined && isObject(entry.strength) ? entry.strength : null;
}

function declaredTools(manifest) {
  return new Set(list(manifest.tools).filter(isObject).map((tool) => tool.name));
}

// The reason an answer to request `id` is refused, or null.
function answerProblem(message, id) {
  if (message.id !== id) return 'wrong-id';
  if (message.type === 'error') return 'provider-error';
  if (message.type !== 'result') return 'unexpected';
  if (message.capability !== 'obligation.check') return 'wrong-capability';
  return null;
}

// The key a run is submitted under: its check, its number and its description.
function runKey(checkKey, number, description) {
  return identityOf({ check: checkKey, run: number, description: identityOf(description) });
}

function sameTools(ran, described) {
  const pairs = (tools) => list(tools).map((tool) => (isObject(tool) ? [tool.name, tool.digest] : [null, null]))
    .sort((a, b) => (String(a[0]) < String(b[0]) ? -1 : String(a[0]) > String(b[0]) ? 1 : 0));
  return Array.isArray(ran) && identityOf(pairs(ran)) === identityOf(pairs(described));
}

// How a report ends the check, or null if the run exited as it was described and the
// provider is to be told. `report` is null when the executor gave none.
function reportEnding(report, run) {
  if (!isObject(report)) return verdict('error');
  if (report.end === 'unavailable') return verdict('unavailable');
  if (report.end !== 'exited') return verdict('error');
  if (identityOf(report.platform === undefined ? null : report.platform) !== identityOf(run.platform)) return verdict('error');
  if (!sameTools(report.tools_ran, run.tools)) return verdict('error');
  return null;
}

// Gives one run to the executor and returns its report, or null.
async function execute(executor, root, asked) {
  const child = processes.start(executor, root);
  const chunks = [];
  let size = 0;
  child.stdout.on('data', (data) => {
    if (size < MAX_REPORT_BYTES) chunks.push(data);
    size += data.length;
  });
  child.stderr.on('data', () => {});
  const ended = new Promise((resolve) => child.stdout.once('close', resolve));
  child.stdin.end(`${JSON.stringify(asked)}\n`);
  const limits = isObject(asked.run.limits) ? asked.run.limits : {};
  const wait = Number.isInteger(limits.wall_ms) && limits.wall_ms > 0 ? limits.wall_ms + EXECUTOR_GRACE_MS : EXECUTOR_DEFAULT_MS;
  const timedOut = await Promise.race([child.exited.then(() => false), processes.pause(wait).then(() => true)]);
  if (timedOut) {
    await processes.endTree(child);
    return { end: 'timed-out' };
  }
  await Promise.race([ended, processes.pause(1000)]);
  if (child.exitCode !== 0 || size > MAX_REPORT_BYTES) return null;
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)).trim();
  } catch (error) {
    return null;
  }
  const read = strictJson.read(text);
  if (read.refused !== undefined || !(read.value instanceof Map)) return null;
  return plain(read.value);
}

async function converse(wire, request) {
  const deadline = request.deadline_ms;
  const waitFor = () => wire.next(performance.now() + deadline);
  wire.send({ type: 'hello', protocol: [PROTOCOL], limits: { max_line_bytes: MAX_LINE_BYTES, deadline_ms: deadline }, echo: ECHO });
  const opening = await waitFor();
  if (opening.reason !== undefined) return refused(opening.reason);
  const hello = opening.message;
  if (hello.type !== 'manifest' || hello.echo !== ECHO || !isObject(hello.manifest) || !Array.isArray(hello.manifest.capabilities)) return refused('bad-manifest');
  const check = {
    platform: request.platform,
    declared: declaredTools(hello.manifest),
    given: new Map(request.tools.filter(isObject).map((tool) => [tool.name, tool.digest])),
    inputs: new Map(request.inputs.filter(isObject).map((input) => [input.path, input.identity])),
    named: namedFiles(request.obligation),
    runs: 0,
    ceiling: ceilingOf(hello.manifest),
    identityOf: (relative) => fileIdentity(request.root, relative),
  };
  const checkKey = identityOf({ obligation: request.obligation, inputs: request.inputs });
  let sent = 1;
  const startId = String(sent);
  wire.send({ type: 'request', id: startId, deadline_ms: deadline, capability: 'obligation.check',
    body: { op: 'start', obligation: request.obligation, inputs: request.inputs, tools: request.tools, platform: request.platform } });
  for (;;) {
    const answer = await waitFor();
    if (answer.reason !== undefined) return refused(answer.reason);
    const wrong = answerProblem(answer.message, String(sent));
    if (wrong !== null) return refused(wrong);
    const body = isObject(answer.message.body) ? answer.message.body : {};
    if (('next' in body) === ('final' in body)) return refused('neither-or-both');
    if ('final' in body) {
      const problem = finalProblem(body.final, check);
      return problem === null ? verdict(body.final.verdict) : refused(problem);
    }
    const problem = runProblem(body.next, check);
    if (problem !== null) return refused(problem);
    check.runs += 1;
    const number = check.runs;
    const report = await execute(request.executor, request.root, { number, run_key: runKey(checkKey, number, body.next), run: body.next });
    const ending = reportEnding(report, body.next);
    if (ending !== null) return ending;
    sent += 1;
    wire.send({ type: 'request', id: String(sent), deadline_ms: deadline, capability: 'obligation.check',
      body: { op: 'run.result', check: startId, run: number, report } });
  }
}

async function runCheck(request) {
  if (!validRequest(request)) throw new Error('a check needs root, provider, obligation, inputs, tools, platform, executor and deadline_ms');
  const given = new Set(request.inputs.filter(isObject).map((input) => input.path));
  if (!namedFiles(request.obligation).every((file) => given.has(file))) return refused('unknown-file');
  const child = processes.start(request.provider, request.root);
  const wire = new Wire(child, { maxLine: MAX_LINE_BYTES, maxLog: MAX_LOG_BYTES, strict: true });
  try {
    return await converse(wire, request);
  } finally {
    wire.send({ type: 'shutdown' });
    wire.close();
    await Promise.race([child.exited, processes.pause(1000)]);
    await processes.endTree(child);
  }
}

module.exports = { runCheck, runKey, reportEnding, answerProblem };
