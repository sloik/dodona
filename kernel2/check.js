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
const { Wire, isObject, MAX_DEPTH } = require('./wire');
const rules = require('./host-rules');
const { ECHO } = require('./session');

const PROTOCOL = '0.2';
const MAX_LINE_BYTES = 1048576;
const MAX_LOG_BYTES = 1048576;
const MAX_REPORT_BYTES = 16 * 1048576;
const MAX_ATTACHMENT_BYTES = 64 * 1048576;
// How long the host waits for the executor: the run's own wall limit and a margin, and
// never more than a day, which is also the wait when the run states no limit. A run it
// stops waiting for ends as timed-out.
const EXECUTOR_MARGIN_MS = 60000;
const EXECUTOR_MOST_MS = 24 * 60 * 60 * 1000;

function refused(reason) {
  return { outcome: 'refused', reason };
}

function verdict(value) {
  return { outcome: 'verdict', verdict: value };
}

// The files the obligation names.
function namedFiles(obligation) {
  return [...obligation.specified_by, ...obligation.targets];
}

// True if `relative` names, from the root, through no symbolic link at any step, a
// regular file of at most MAX_ATTACHMENT_BYTES. The path has passed the path check.
function isRegularFile(root, relative) {
  const parts = relative.split('/');
  let at = root;
  try {
    for (let i = 0; i < parts.length; i += 1) {
      at = path.join(at, parts[i]);
      const last = i === parts.length - 1;
      const status = fs.lstatSync(at);
      if (status.isSymbolicLink()) return false;
      if (!last && !status.isDirectory()) return false;
      if (last && !(status.isFile() && status.size <= MAX_ATTACHMENT_BYTES)) return false;
    }
    return true;
  } catch (error) {
    return false;
  }
}

// The identity of a regular file's bytes under the root, or null. Opened without
// following a link and without waiting, and looked at again once open.
function fileIdentity(root, relative) {
  const flags = fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0) | (fs.constants.O_NONBLOCK || 0);
  let handle;
  try {
    handle = fs.openSync(path.join(root, relative), flags);
    const status = fs.fstatSync(handle);
    if (!status.isFile() || status.size > MAX_ATTACHMENT_BYTES) return null;
    const hash = crypto.createHash('sha256');
    const buffer = Buffer.alloc(65536);
    let read;
    let total = 0;
    while ((read = fs.readSync(handle, buffer, 0, buffer.length, null)) > 0) {
      total += read;
      if (total > MAX_ATTACHMENT_BYTES) return null;
      hash.update(buffer.subarray(0, read));
    }
    return `sha256:${hash.digest('hex')}`;
  } catch (error) {
    return null;
  } finally {
    if (handle !== undefined) fs.closeSync(handle);
  }
}

// The reason an answer to request `id` is refused, or null.
function answerProblem(message, id) {
  if (message.id !== id) return 'wrong-id';
  if (message.type === 'error') return 'provider-error';
  if (message.type !== 'result') return 'unexpected';
  if (message.capability !== 'obligation.check') return 'wrong-capability';
  if (!isObject(message.body)) return 'unexpected';
  return null;
}

// The key a run is submitted under: its check, its number and its description.
function runKey(checkKey, number, description) {
  return identityOf({ check: checkKey, run: number, description: identityOf(description) });
}

function sameTools(ran, described) {
  const pairs = (tools) => (Array.isArray(tools) ? tools : []).map((tool) => (isObject(tool) ? [tool.name, tool.digest] : [null, null]))
    .sort((a, b) => (String(a[0]) < String(b[0]) ? -1 : String(a[0]) > String(b[0]) ? 1 : 0));
  return Array.isArray(ran) && identityOf(pairs(ran)) === identityOf(pairs(described));
}

// How a report ends the check, or null if the run exited as it was described and the
// provider is to be told. `report` is null when the executor gave none that can be read.
function reportEnding(report, run) {
  if (!isObject(report)) return verdict('error');
  if (report.end === 'unavailable') return verdict('unavailable');
  if (report.end !== 'exited') return verdict('error');
  if (identityOf(report.platform === undefined ? null : report.platform) !== identityOf(run.platform)) return verdict('error');
  if (!sameTools(report.tools_ran, run.tools)) return verdict('error');
  return null;
}

// A report read strictly, as messages are read: one line, one object; or null.
function readReport(bytes) {
  const line = bytes.length > 0 && bytes[bytes.length - 1] === 0x0a ? bytes.subarray(0, bytes.length - 1) : bytes;
  if (line.includes(0x0a) || line.includes(0x0d) || (line.length >= 3 && line[0] === 0xef && line[1] === 0xbb && line[2] === 0xbf)) return null;
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(line);
  } catch (error) {
    return null;
  }
  const read = strictJson.read(text, { maxDepth: MAX_DEPTH });
  if (read.refused !== undefined || !(read.value instanceof Map)) return null;
  return plain(read.value);
}

function executorWait(run) {
  const wall = isObject(run.limits) ? run.limits.wall_ms : undefined;
  return Number.isSafeInteger(wall) && wall > 0 ? Math.min(wall + EXECUTOR_MARGIN_MS, EXECUTOR_MOST_MS) : EXECUTOR_MOST_MS;
}

// Gives one run to the executor and returns its report, or null. Every process the
// executor started is ended once it has answered, or once the host stops waiting.
async function execute(executor, root, asked) {
  const child = processes.start(executor, root);
  const chunks = [];
  let size = 0;
  child.stdout.on('data', (data) => {
    if (size <= MAX_REPORT_BYTES) chunks.push(data);
    size += data.length;
  });
  child.stderr.on('data', () => {});
  const ended = new Promise((resolve) => child.stdout.once('close', resolve));
  child.stdin.end(`${JSON.stringify(asked)}\n`);
  let timer;
  const stopped = new Promise((resolve) => {
    timer = setTimeout(() => resolve(true), executorWait(asked.run));
  });
  const timedOut = await Promise.race([child.exited.then(() => false), stopped]);
  clearTimeout(timer);
  if (!timedOut) await Promise.race([ended, processes.pause(1000)]);
  await processes.endTree(child);
  if (timedOut) return { end: 'timed-out' };
  if (child.exitCode !== 0 || size > MAX_REPORT_BYTES) return null;
  return readReport(Buffer.concat(chunks));
}

async function converse(wire, request) {
  const deadline = request.deadline_ms;
  const waitFor = () => wire.next(performance.now() + deadline);
  const send = (message) => wire.send(message, performance.now() + deadline);
  const helloSent = await send({ type: 'hello', protocol: [PROTOCOL], limits: { max_line_bytes: MAX_LINE_BYTES, deadline_ms: deadline }, echo: ECHO });
  if (helloSent !== null) return refused(helloSent);
  const opening = await waitFor();
  if (opening.reason !== undefined) return refused(opening.reason);
  const hello = opening.message;
  if (hello.type !== 'manifest' || hello.echo !== ECHO) return refused('bad-manifest');
  const badManifest = rules.manifestProblem(hello.manifest);
  if (badManifest !== null) return refused(badManifest);
  const check = {
    platform: request.platform,
    declared: rules.declaredTools(hello.manifest),
    given: new Map(request.tools.map((tool) => [tool.name, tool.digest])),
    inputs: new Map(request.inputs.map((input) => [input.path, input.identity])),
    named: namedFiles(request.obligation),
    runs: 0,
    ceiling: rules.ceilingOf(hello.manifest),
    isRegularFile: (relative) => isRegularFile(request.root, relative),
    identityOf: (relative) => fileIdentity(request.root, relative),
  };
  const checkKey = identityOf({ obligation: request.obligation, inputs: request.inputs });
  let sent = 1;
  const startId = String(sent);
  const startSent = await send({ type: 'request', id: startId, deadline_ms: deadline, capability: 'obligation.check',
    body: { op: 'start', obligation: request.obligation, inputs: request.inputs, tools: request.tools, platform: request.platform } });
  if (startSent !== null) return refused(startSent);
  for (;;) {
    const answer = await waitFor();
    if (answer.reason !== undefined) return refused(answer.reason);
    const wrong = answerProblem(answer.message, String(sent));
    if (wrong !== null) return refused(wrong);
    const body = isObject(answer.message.body) ? answer.message.body : {};
    if (('next' in body) === ('final' in body)) return refused('neither-or-both');
    if ('final' in body) {
      const problem = rules.finalProblem(body.final, check);
      return problem === null ? verdict(body.final.verdict) : refused(problem);
    }
    const problem = rules.runProblem(body.next, check);
    if (problem !== null) return refused(problem);
    check.runs += 1;
    const number = check.runs;
    const report = await execute(request.executor, request.root, { number, run_key: runKey(checkKey, number, body.next), run: body.next });
    const ending = reportEnding(report, body.next);
    if (ending !== null) return ending;
    sent += 1;
    const resultSent = await send({ type: 'request', id: String(sent), deadline_ms: deadline, capability: 'obligation.check',
      body: { op: 'run.result', check: startId, run: number, report } });
    if (resultSent !== null) return refused(resultSent);
  }
}

async function runCheck(request) {
  const badInput = rules.inputProblem(request);
  if (badInput !== null) return refused(badInput);
  const given = new Set(request.inputs.map((input) => input.path));
  if (!namedFiles(request.obligation).every((file) => given.has(file))) return refused('unknown-file');
  const child = processes.start(request.provider, request.root);
  const wire = new Wire(child, { maxLine: MAX_LINE_BYTES, maxLog: MAX_LOG_BYTES, strict: true });
  try {
    return await converse(wire, request);
  } finally {
    wire.post({ type: 'shutdown' });
    wire.close();
    await Promise.race([child.exited, processes.pause(1000)]);
    await processes.endTree(child);
  }
}

module.exports = { runCheck, runKey, reportEnding, answerProblem, readReport, isRegularFile, executorWait };
