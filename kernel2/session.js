'use strict';
// One provider session (conformance/README.md, "Session").
//
//     session --deadline-ms N --max-line N --max-log N -- <provider command and arguments>
//
// Starts the provider, sends hello, requires the manifest with the echo unchanged,
// sends one decision.index request, requires its result, sends shutdown, and ends
// every process in the provider's process group (Unix) or below it (Windows). One
// deadline covers the whole session, sending as well as waiting.

const processes = require('./processes');
const { Wire, isObject } = require('./wire');

const PROTOCOL = '0.2';
// Non-ASCII letters and control characters, so that a provider that does not read
// and write text exactly as it is sent is refused before anything is asked of it.
const ECHO = 'Zażółć gęślą jaźń \u0001\u0007\t\u001b\u007f Ωμέγα 日本語 \u{1F642}';

// The options of the command, or null if they are not as the contract gives them.
function parseArguments(argv) {
  const split = argv.indexOf('--');
  if (split === -1 || split === argv.length - 1) return null;
  const options = argv.slice(0, split);
  const values = {};
  for (let i = 0; i < options.length; i += 2) {
    const name = options[i];
    const value = options[i + 1];
    if (!['--deadline-ms', '--max-line', '--max-log'].includes(name) || value === undefined || !/^\d+$/.test(value)) return null;
    values[name] = Number(value);
  }
  if (values['--deadline-ms'] === undefined || values['--max-line'] === undefined || values['--max-log'] === undefined) return null;
  return { deadlineMs: values['--deadline-ms'], maxLine: values['--max-line'], maxLog: values['--max-log'], provider: argv.slice(split + 1) };
}

// The reason a manifest answer is refused, or null.
function manifestProblem(message) {
  if (message.type !== 'manifest' || message.echo !== ECHO || !isObject(message.manifest)) return 'bad-manifest';
  return null;
}

// The reason the answer to the one request is refused, or null.
function answerProblem(message) {
  if (message.id !== '1') return 'wrong-id';
  if (message.type === 'error') return 'provider-error';
  if (message.type !== 'result') return 'unexpected';
  if (message.capability !== 'decision.index') return 'wrong-capability';
  return null;
}

// After shutdown the provider has up to this long, or until the deadline if that is
// nearer, to exit. Its answer stands either way; one still running is then ended.
const SHUTDOWN_GRACE_MS = 1000;

// Waits after shutdown until the provider exits, or its grace is over. Anything more
// it writes in that time is `unexpected`.
async function awaitExit(child, wire, until) {
  const graceEnds = Math.min(until, performance.now() + SHUTDOWN_GRACE_MS);
  for (;;) {
    if (wire.hasMore()) return 'unexpected';
    if (child.hasExited) {
      // What it wrote just before it exited may still be on its way.
      await wire.change(performance.now() + 100);
      return wire.hasMore() ? 'unexpected' : null;
    }
    if (performance.now() >= graceEnds) return null;
    await Promise.race([wire.change(graceEnds), child.exited]);
  }
}

async function converse(child, wire, options, until) {
  const helloSent = await wire.send({ type: 'hello', protocol: [PROTOCOL], limits: { max_line_bytes: options.maxLine, deadline_ms: options.deadlineMs }, echo: ECHO }, until);
  if (helloSent !== null) return helloSent;
  const opening = await wire.next(until);
  if (opening.reason !== undefined) return opening.reason;
  const badManifest = manifestProblem(opening.message);
  if (badManifest !== null) return badManifest;
  const requestSent = await wire.send({ type: 'request', id: '1', deadline_ms: options.deadlineMs, capability: 'decision.index', body: { files: [] } }, until);
  if (requestSent !== null) return requestSent;
  const answer = await wire.next(until);
  if (answer.reason !== undefined) return answer.reason;
  const badAnswer = answerProblem(answer.message);
  if (badAnswer !== null) return badAnswer;
  wire.post({ type: 'shutdown' });
  wire.close();
  return awaitExit(child, wire, until);
}

async function runSession(argv) {
  const options = parseArguments(argv);
  if (options === null) throw new Error('usage: session --deadline-ms N --max-line N --max-log N -- <provider command>');
  const until = performance.now() + options.deadlineMs;
  const child = processes.start(options.provider, process.cwd());
  const wire = new Wire(child, { maxLine: options.maxLine, maxLog: options.maxLog, strict: false });
  let reason;
  try {
    reason = await converse(child, wire, options, until);
  } finally {
    wire.post({ type: 'shutdown' });
    wire.close();
    await processes.endTree(child);
  }
  const outcome = reason === null ? { outcome: 'ok' } : { outcome: 'error', reason };
  return { ...outcome, ...wire.logSummary() };
}

module.exports = { runSession, parseArguments, manifestProblem, answerProblem, ECHO };
