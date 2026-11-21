'use strict';
// The first parts of the `run` command (conformance/README.md, "How a project's run is
// judged"; decision 0034): its additions to step 1, and the plan of step 10. The command
// is not served yet, and dodona-kernel2.js offers no `run`; this module is reached only
// through its tests (test-run.js).
//
// The run command takes the status command's input with `ledger`, `executor` and,
// where wanted, `transcript`. These are checked first, before the status command's own
// checks of step 1 (those that need `root` only when it is a folder), and so before any
// provider's code is read or any provider started. Every rule broken here is `bad-input`.

const fs = require('node:fs');
const path = require('node:path');
const unicode = require('./unicode');
const { isObject } = require('./wire');
const { compareUnits } = require('./canonical');
const { identityOf } = require('./identity');
const rules = require('./host-rules');
const {
  answerProblem, runKey, isRegularFile, fileIdentity, namedFiles, reportEnding, readReport,
} = require('./check');
const processes = require('./processes');
const crypto = require('node:crypto');
const ledgerFile = require('./ledger-file');

// How long the executor is waited for (step 12): the longest `wall_ms` of the batch,
// below 0 read as 0, and 60 seconds more; a day if a run states none; never more.
const EXECUTOR_MARGIN_MS = 60000;
const EXECUTOR_MOST_MS = 24 * 60 * 60 * 1000;
const {
  readInput, isRelative, checkInput, isDirectory, fileId, stepsOf, snapshotOf, endSession, reportOf, rereadOf, Stop,
} = require('./project-status');

// The statuses that are a current result: reused, nothing sent for them.
const CURRENT = ['passed', 'failed', 'conflict'];
// A reason that says the session itself broke: every check on it is in doubt, and the
// whole run is refused with it (step 11). Any other reason refuses one check.
const SESSION_BROKE = ['deadline', 'closed', 'framing', 'too-long', 'encoding', 'malformed', 'not-an-integer', 'duplicate-key',
  'too-deep', 'wrong-id', 'wrong-capability', 'unexpected', 'provider-error'];
// What a checked obligation can end as, in the order `counts` gives them.
const OUTCOMES = ['passed', 'failed', 'error', 'unavailable', 'unsupported', 'refused'];

function isString(value) {
  return typeof value === 'string';
}

function own(object, key) {
  return isObject(object) && Object.hasOwn(object, key) ? object[key] : undefined;
}

function refuse(detail) {
  throw new Stop('bad-input', detail);
}

// A path as a disk that ignores case and Unicode normalization compares names: NFC of
// the case-folded NFC. (unicode.caselessKey is NFD-based, for the path check's
// collisions, and is not this rule.)
function diskName(text) {
  return unicode.fromCodePoints(unicode.nfc(unicode.fold(unicode.nfc(unicode.toCodePoints(text)))));
}

// True when a segment of a relative path ends in an ASCII dot or space: a name some
// disks store without that ending, so that it would write over another path's file.
function endsInDotOrSpace(rel) {
  return rel.split('/').some((segment) => segment.endsWith('.') || segment.endsWith(' '));
}

// True unless a step of the path, looked at without following it, is a symbolic link.
// A step that is not there, or cannot be looked at, ends the walk: what lies beyond it is
// no link, and reading or appending then finds it absent or unreadable, as the status
// command reads the owner's ledger.
function reachedWithoutLink(root, rel) {
  for (const step of stepsOf(root, rel)) {
    let status;
    try {
      status = fs.lstatSync(step);
    } catch (error) {
      return true;
    }
    if (status.isSymbolicLink()) return false;
  }
  return true;
}

// Why the transcript cannot be written as a new file in a folder that is there, reached
// without a link, or null. Every folder on its way must be shown to be a folder, and the
// transcript itself must be shown not to be there: a link to nothing is there.
function transcriptPlaceProblem(root, rel) {
  const steps = stepsOf(root, rel);
  for (const step of steps.slice(0, -1)) {
    let status;
    try {
      status = fs.lstatSync(step);
    } catch (error) {
      return `is not in a folder that is there (${error.code || error.message})`;
    }
    if (status.isSymbolicLink()) return 'is reached through a link';
    if (!status.isDirectory()) return 'is not in a folder';
  }
  try {
    fs.lstatSync(steps[steps.length - 1]);
  } catch (error) {
    return error.code === 'ENOENT' ? null : `cannot be shown not to be there (${error.code || error.message})`;
  }
  return 'is already there: a transcript is written only as a new file';
}

// The run command's own fields, checked before the status command's step 1.
function checkRunInput(asked) {
  if (!isObject(asked)) refuse('the input is not one JSON object read strictly');
  const ledgers = own(asked, 'ledgers');
  const ledger = own(asked, 'ledger');
  const ownerRel = own(asked, 'owner_ledger');
  if (!Array.isArray(ledgers) || !ledgers.every(isString)) refuse('ledgers is not a list of strings');
  if (!isRelative(ledger)) refuse('ledger is not a relative path');
  // Membership is by the path as given: what this run records is what the next run reads.
  if (!ledgers.includes(ledger)) refuse('ledger is not one of ledgers');
  if (!isRelative(ownerRel)) refuse('owner_ledger is not a relative path');
  // The ledger written and the owner's it must not be: each spelt as no disk would alter it.
  if (endsInDotOrSpace(ledger) || endsInDotOrSpace(ownerRel)) refuse('ledger or owner_ledger has a segment ending in a dot or a space');
  if (diskName(ledger) === diskName(ownerRel)) refuse("ledger names the owner's ledger, as a disk that ignores case and normalization compares names");
  const executor = own(asked, 'executor');
  // A command none of whose words holds a NUL, which no program's arguments can carry.
  if (!Array.isArray(executor) || executor.length === 0 || !executor.every((word) => isString(word) && !word.includes('\u0000'))) {
    refuse('executor is not a non-empty list of strings without NUL');
  }
  const given = Object.hasOwn(asked, 'transcript');
  const transcript = asked.transcript;
  if (given) {
    if (!isRelative(transcript)) refuse('transcript is not a relative path');
    // The transcript, and every path it is compared with, spelt as no disk would alter it.
    const project = own(asked, 'project');
    const spelt = [transcript, ...ledgers.filter(isRelative), ...(isRelative(project) ? [project] : [])];
    if (spelt.some(endsInDotOrSpace)) refuse('with a transcript, the transcript, a ledger or the project file has a segment ending in a dot or a space');
    // No ledger, no ledger's lock (the owner's included), not the project file.
    const taken = [...ledgers, ownerRel].flatMap((rel) => [rel, `${rel}.lock`]);
    if (isString(project)) taken.push(project);
    const name = diskName(transcript);
    const clash = taken.find((rel) => diskName(rel) === name);
    if (clash !== undefined) refuse(`transcript names ${JSON.stringify(clash)}, as a disk that ignores case and normalization compares names`);
  }
  // What needs the disk, only once root is a folder: otherwise the status command's own
  // step 1 refuses it, and no path is ever resolved against the working folder.
  const root = own(asked, 'root');
  if (!isString(root) || !isDirectory(root)) return;
  if (!reachedWithoutLink(root, ledger)) refuse('ledger is reached through a link');
  const ledgerId = fileId(path.join(root, ledger));
  if (ledgerId !== null && ledgerId === fileId(path.join(root, ownerRel))) {
    refuse("ledger is the owner's ledger, as the operating system identifies files");
  }
  if (given) {
    const problem = transcriptPlaceProblem(root, transcript);
    if (problem !== null) refuse(`transcript ${problem}`);
  }
}

// Step 1 of the run command: its own fields, then the status command's step 1. Returns
// what that gives, the code digest of each provider by name; throws a Stop otherwise.
function preflight(asked) {
  checkRunInput(asked);
  return checkInput(asked);
}

// Step 10, the plan, from what the status command's steps 2 to 10 judged: the status
// rules' own report says which obligation has a current result. Each obligation the
// providers listed is either reused (passed, failed or conflict) or to be checked
// (unknown), taken sorted by binding and then name. A name both listed and rejected is
// checked as listed; a rejected name not listed is never checked, and only counted.
function planOf(snapshot) {
  const listed = [...snapshot.obligations.listed].sort((a, b) => compareUnits(a.binding, b.binding) || compareUnits(a.name, b.name));
  const check = [];
  const reused = [];
  for (const { binding, name } of listed) {
    const status = own(own(snapshot.report.obligations, name), 'status');
    // The report names every obligation judged, as its own entry. One it lacks (such as a
    // name the report's object could not hold as its own key) is a fault here, never a
    // reason to check or to reuse.
    if (!CURRENT.includes(status) && status !== 'unknown') {
      throw new Error(`the status report gives no status of its own for the listed obligation ${JSON.stringify(name)}`);
    }
    if (CURRENT.includes(status)) reused.push({ binding, name, status });
    else check.push({ binding, name });
  }
  return { obligations: listed.length, check, reused, not_checkable: snapshot.obligations.unchecked };
}

// `counts`, once each planned check has its outcome, in the order the checks were taken.
// With nothing to check, `countsOf(plan, [])` is the whole of it.
// Each outcome is read by its position, so a hole in the list (which `every` and `filter`
// would pass over) is a missing outcome, never one counted as nothing.
function countsOf(plan, outcomes) {
  const checked = plan.check.length;
  const given = Array.isArray(outcomes) && outcomes.length === checked
    && plan.check.every((_, at) => Object.hasOwn(outcomes, at) && OUTCOMES.includes(outcomes[at]));
  if (!given) throw new Error('every planned check needs exactly one outcome');
  const counts = { obligations: plan.obligations, reused: plan.reused.length, checked };
  for (const outcome of OUTCOMES) counts[outcome] = 0;
  for (let at = 0; at < checked; at += 1) counts[outcomes[at]] += 1;
  counts.not_checkable = plan.not_checkable.length;
  return counts;
}

// Steps 1 to 10. The providers are asked as the status command asks them, except that
// the session of every binding that lists obligation.check stays open after its answer
// (step 5 of the run), whether or not anything of it is planned: `sessions`, in the
// order the bindings were asked, each with what its checks start from. Whoever is given
// them ends them with closeSessions; a refusal before that ends them here.
async function planRun(asked, record = null) {
  const digests = preflight(asked);
  const sessions = [];
  try {
    const snapshot = await snapshotOf(asked, digests, sessions, record);
    return { digests, snapshot, plan: planOf(snapshot), sessions };
  } catch (error) {
    throw await afterClosing(error, sessions);
  }
}

// Ends every kept session: shutdown, a moment to exit, every process ended. The list is
// emptied first, so no session is ended twice, and each is then ended in turn, in the
// order the bindings were asked, whether or not one before it could be: ending one can
// fail (on Windows, reading the process table). Failures are thrown together afterwards,
// as one AggregateError naming each binding and process.
async function closeSessions(sessions) {
  const failures = [];
  for (const session of sessions.splice(0)) {
    try {
      await endSession(session.wire, session.child);
    } catch (error) {
      failures.push({ binding: session.binding.name, pid: session.child.pid, error });
    }
  }
  if (failures.length > 0) {
    const said = failures.map((failure) => `${failure.binding} (process ${failure.pid}): ${failure.error && failure.error.message}`);
    const error = new AggregateError(failures.map((failure) => failure.error), `kept sessions not all ended: ${said.join('; ')}`);
    error.failures = failures;
    throw error;
  }
}

// On a refusal: every kept session ended, and the refusal given as it was. A failure to
// end them does not take its place; it rides along as the refusal's `cleanup`.
async function afterClosing(error, sessions) {
  try {
    await closeSessions(sessions);
  } catch (cleanup) {
    if (error !== null && typeof error === 'object') error.cleanup = cleanup;
  }
  return error;
}

// Step 11: checks on the sessions kept at step 5. A step of a check is one of
//   {outcome: 'next', number, run_key, run}       a run to be given to the executor
//   {outcome: 'final', verdict, strength}          the final, as the provider gave it
//   {outcome: 'refused', reason}                   this check ends with no verdict
// and a reason that says the session broke is thrown as a Stop: the whole run is refused.

// The obligation as enumerated, without `inputs` and with its binding: each own field
// copied as data, whatever its name.
function asEnumerated(item, binding) {
  const out = {};
  const put = (key, value) => Object.defineProperty(out, key, { value, enumerable: true, writable: true, configurable: true });
  for (const key of Object.keys(item)) if (key !== 'inputs') put(key, item[key]);
  put('binding', binding);
  return out;
}

// The start of a check of `name` on its binding's kept session: its inputs are F, the
// obligation's own `inputs` with the identities the enumeration request gave them; its
// tools and platform those the session was kept with.
function startBody(session, name) {
  const item = session.obligations.find((each) => each.name === name);
  if (item === undefined) throw new Error(`${JSON.stringify(name)} was not enumerated on binding ${session.binding.name}`);
  const files = new Map(session.request.files.map((file) => [file.path, file.identity]));
  const inputs = item.inputs.map((rel) => ({ path: rel, identity: files.get(rel) }));
  return { op: 'start', obligation: asEnumerated(item, session.binding.name), inputs, tools: session.tools, platform: session.platform };
}

function brokeOff(session, reason) {
  if (!SESSION_BROKE.includes(reason)) throw new Error(`${reason} is not a reason a session breaks with`);
  session.broken = reason;
  throw new Stop(reason, `binding ${session.binding.name}: the session broke`);
}

// One request of a check on its session, under the session's next id, and what its
// answer makes of the check, by the host checks' rules.
async function exchange(check, body) {
  const { session } = check;
  if (session.broken !== undefined) throw new Error(`binding ${session.binding.name}: the session has already broken (${session.broken})`);
  // A provider speaks only to answer. Anything it sent while the session waited idle, a
  // whole message or part of one, is `unexpected`, and nothing more is sent to it.
  if (session.wire.hasMore()) brokeOff(session, 'unexpected');
  const id = String(session.next_id);
  session.next_id += 1;
  if (check.start_id === null) check.start_id = id;
  const deadline = session.deadline_ms;
  const sent = await session.wire.send({ type: 'request', id, deadline_ms: deadline, capability: 'obligation.check', body }, performance.now() + deadline);
  if (sent !== null) brokeOff(session, sent);
  const answer = await session.wire.next(performance.now() + deadline);
  if (answer.reason !== undefined) brokeOff(session, answer.reason);
  const wrong = answerProblem(answer.message, id);
  if (wrong !== null) brokeOff(session, wrong);
  const reply = answer.message.body;
  if (('next' in reply) === ('final' in reply)) return { outcome: 'refused', reason: 'neither-or-both' };
  if ('final' in reply) {
    const problem = rules.finalProblem(reply.final, check.rules);
    return problem === null ? { outcome: 'final', verdict: reply.final.verdict, strength: reply.final.strength } : { outcome: 'refused', reason: problem };
  }
  const problem = rules.runProblem(reply.next, check.rules);
  if (problem !== null) return { outcome: 'refused', reason: problem };
  check.rules.runs += 1;
  const number = check.rules.runs;
  return { outcome: 'next', number, run_key: runKey(check.key, number, reply.next), run: reply.next };
}

// Starts the check of one planned obligation on its binding's kept session. A binding
// with no kept session (it does not list obligation.check), or whose manifest does not
// offer obligation.check, is refused, and nothing is sent.
async function startCheck(sessions, planned, root) {
  const session = sessions.find((each) => each.binding.name === planned.binding);
  if (session === undefined || !session.offers_check) return { check: null, step: { outcome: 'refused', reason: 'check-not-offered' } };
  const body = startBody(session, planned.name);
  const check = {
    session,
    name: planned.name,
    start_id: null,
    key: identityOf({ obligation: body.obligation, inputs: body.inputs }),
    rules: {
      platform: session.platform,
      declared: rules.declaredTools(session.manifest),
      given: new Map(session.tools.map((tool) => [tool.name, tool.digest])),
      inputs: new Map(body.inputs.map((input) => [input.path, input.identity])),
      named: namedFiles(body.obligation),
      runs: 0,
      ceiling: rules.ceilingOf(session.manifest),
      isRegularFile: (relative) => isRegularFile(root, relative),
      identityOf: (relative) => fileIdentity(root, relative),
    },
  };
  return { check, step: await exchange(check, body) };
}

// Step 12: batches.

function batchWait(runs) {
  let longest = 0;
  for (const { run } of runs) {
    const wall = isObject(run.limits) ? run.limits.wall_ms : undefined;
    if (!Number.isSafeInteger(wall)) return EXECUTOR_MOST_MS;
    longest = Math.max(longest, wall, 0);
  }
  return Math.min(longest + EXECUTOR_MARGIN_MS, EXECUTOR_MOST_MS);
}

// What the executor's answer to one batch gives each run of it, in the batch's order:
// `{report}` to be read as the host checks read one, or `{verdict}` for its check. The
// executor's outcome is `{timedOut: true}`, `{answer}` (one object read strictly from
// its first line, the executor having exited with 0), or anything else (it could not
// start, exited otherwise, or printed nothing that can be read).
function batchReports(runs, outcome) {
  const all = (verdict) => runs.map(() => ({ verdict }));
  if (isObject(outcome) && outcome.timedOut === true) return all('error');
  const answer = isObject(outcome) ? outcome.answer : undefined;
  if (!isObject(answer) || answer.ended !== true || !Array.isArray(answer.reports)) return all('unavailable');
  const keys = new Set(runs.map((run) => run.run_key));
  const reports = new Map();
  for (const item of answer.reports) {
    if (!isObject(item) || !isString(item.run_key) || !keys.has(item.run_key) || !Object.hasOwn(item, 'report')) return all('error');
    if (reports.has(item.run_key)) return all('error');
    reports.set(item.run_key, item.report);
  }
  return runs.map((run) => (reports.has(run.run_key) ? { report: reports.get(run.run_key) } : { verdict: 'error' }));
}

// The executor command for one batch (step 12), in `root`, in a process group (job) of its
// own, which is ended on every way out. Its answer is taken only once, within `waitMs`,
// the batch has been written to it whole, it has exited, and its standard output has
// come to its end. Only the first line is kept, however long; what follows is read and
// dropped. An output that fails, or is closed without coming to its end, is no answer.
// Returns what checkAll expects of `execute`: `{timedOut: true}` when that did not all
// happen in time; `{answer}` when it exited with 0 and its first line is one object read
// strictly (ended by a line feed alone, no byte-order mark, no fraction, no key twice);
// `{}` when it could not start, could not be given the batch, exited otherwise, or
// printed nothing that can be read. `start` and `end` are processes.start and
// processes.endTree unless a test gives others.
async function executeBatch(executor, root, batch, waitMs, { start = processes.start, end = processes.endTree } = {}) {
  const child = start(executor, root);
  if (child.pid === undefined) {
    await child.exited;
    return {};
  }
  let timer;
  try {
    const kept = [];
    let lineDone = false;
    child.stdout.on('data', (data) => {
      if (lineDone) return;
      const at = data.indexOf(0x0a);
      kept.push(at < 0 ? data : data.subarray(0, at + 1));
      if (at >= 0) lineDone = true;
    });
    child.stderr.on('data', () => {});
    // 'eof' once the output has come to its end; 'broken' if it fails or closes first.
    const outputClosed = new Promise((resolve) => {
      let ended = false;
      child.stdout.once('end', () => {
        ended = true;
        resolve('eof');
      });
      child.stdout.once('error', () => resolve('broken'));
      child.stdout.once('close', () => resolve(ended ? 'eof' : 'broken'));
    });
    const written = new Promise((resolve) => {
      child.stdin.once('error', () => resolve(false));
      child.stdin.end(`${JSON.stringify(batch)}\n`, (error) => resolve(!error));
    });
    const deadline = new Promise((resolve) => {
      timer = setTimeout(() => resolve('timed-out'), waitMs);
    });
    const done = Promise.all([written, child.exited, outputClosed]).then(([whole, , output]) => (!whole ? 'not-written' : output !== 'eof' ? 'not-read' : 'done'));
    const how = await Promise.race([done, deadline]);
    if (how === 'timed-out') return { timedOut: true };
    if (how !== 'done' || child.exitCode !== 0 || !lineDone) return {};
    const answer = readReport(Buffer.concat(kept));
    return answer === null ? {} : { answer };
  } finally {
    clearTimeout(timer);
    await end(child);
  }
}

// Every planned check, from its start to its end, on the sessions kept at step 5: the
// runs every open check asks for at one time form one batch, given to `execute(batch,
// waitMs)` once; each report is read and passed back to its provider one at a time, in
// the order the checks were started; a check that asks for another run gets it in the
// next batch. Returns, in the order of the plan, each check's end: `{binding, name,
// outcome}` with `outcome` a verdict or `refused`, and for a provider's final its
// `strength` as given. A session that breaks refuses the whole run (a Stop is thrown).
async function checkAll(sessions, plan, root, execute) {
  const open = [];
  for (const planned of plan.check) {
    const { check, step } = await startCheck(sessions, planned, root);
    open.push({ planned, check, step, end: null });
  }
  const endOf = (record) => {
    const { step } = record;
    if (step.outcome === 'final') record.end = { outcome: step.verdict, strength: step.strength };
    else if (step.outcome === 'refused') record.end = { outcome: 'refused', reason: step.reason };
  };
  open.forEach(endOf);
  for (;;) {
    const waiting = open.filter((record) => record.end === null);
    if (waiting.length === 0) break;
    const runs = waiting.map((record) => ({ number: record.step.number, run_key: record.step.run_key, run: record.step.run }));
    const given = batchReports(runs, await execute({ runs }, batchWait(runs)));
    for (let at = 0; at < waiting.length; at += 1) {
      const record = waiting[at];
      const ending = given[at].verdict !== undefined ? { verdict: given[at].verdict } : reportEnding(given[at].report, record.step.run);
      if (ending !== null) {
        record.end = { outcome: ending.verdict };
        continue;
      }
      record.step = await exchange(record.check, { op: 'run.result', check: record.check.start_id, run: record.step.number, report: given[at].report });
      endOf(record);
    }
  }
  return open.map(({ planned, end }) => ({ binding: planned.binding, name: planned.name, ...end }));
}

// Step 13: recording.

// The level an evidence entry states, from the final's rank as the host checks read it.
const LEVEL_OF_RANK = { documented: 'asserted', sampled: 'sampled', bounded: 'bounded', exhaustive: 'proven' };
const LEDGER_WAIT_MS = 60000;

// Each input read again (following links, as the kit notes) only if it is a regular file.
function stillTheSame(root, inputs) {
  return inputs.every(({ path: rel, identity }) => {
    try {
      const where = path.join(root, rel);
      if (!fs.statSync(where).isFile()) return false;
      return `sha256:${crypto.createHash('sha256').update(fs.readFileSync(where)).digest('hex')}` === identity;
    } catch (error) {
      return false;
    }
  });
}

// For each check, in the order the checks were started (`ends` is checkAll's answer),
// whose verdict is passed or failed: each input file read again, and the verdict kept
// only if every one still has the identity it was keyed with (otherwise `error`); then
// one evidence entry for each kept verdict, all in one append to the run's ledger, once
// it is shown again to be reached without a link and not the owner's ledger. Nothing is
// written when nothing is kept. Returns each check's outcome, in the same order, for
// countsOf. A ledger that cannot be appended to is `ledger-not-written`.
function recordVerdicts(asked, sessions, snapshot, ends, { waitMs = LEDGER_WAIT_MS, io = fs, release } = {}) {
  const { root, site } = asked;
  const outcomes = [];
  const entries = [];
  for (const end of ends) {
    if (end.outcome !== 'passed' && end.outcome !== 'failed') {
      outcomes.push(end.outcome);
      continue;
    }
    const session = sessions.find((each) => each.binding.name === end.binding);
    if (!stillTheSame(root, startBody(session, end.name).inputs)) {
      outcomes.push('error');
      continue;
    }
    outcomes.push(end.outcome);
    const { preimage } = own(snapshot.judged.obligations, end.name);
    entries.push({
      kind: 'evidence',
      body: {
        obligation: end.name,
        preimage,
        core_key: identityOf(preimage),
        platform: `${site.platform.os}/${site.platform.arch}`,
        verdict: end.outcome,
        writer: site.writer,
        strength: end.strength,
        level: LEVEL_OF_RANK[end.strength.rank],
      },
    });
  }
  if (entries.length === 0) return outcomes;
  // Asked before the folders are made, and again under the ledger's lock.
  const problem = () => ledgerProblem(root, asked.ledger, asked.owner_ledger);
  const early = problem();
  if (early !== null) throw new Stop('ledger-not-written', early);
  let written;
  try {
    written = ledgerFile.appendAll(path.join(root, asked.ledger), entries, waitMs, { check: problem, io, release });
  } catch (error) {
    throw new Stop('ledger-not-written', `${asked.ledger}: ${error.code || error.message}`);
  }
  if (written.refused === 'not-unlocked') {
    // Only what was seen is said: the append under the lock, then a lock not released.
    const held = written.held;
    const under = held.appended !== undefined ? 'its entries were written and flushed'
      : held.rolled_back === true ? `not written (${held.detail}), and cut back` : `not written (${held.refused}${held.detail ? `: ${held.detail}` : ''})`;
    throw new Stop('ledger-not-written', `${asked.ledger}: ${under}; the lock could not be released: ${written.detail}`);
  }
  if (written.refused !== undefined) {
    const said = [written.refused, written.detail, written.rolled_back === false ? 'the ledger could not be cut back to what it held' : null];
    throw new Stop('ledger-not-written', `${asked.ledger}: ${said.filter(Boolean).join('; ')}`);
  }
  return outcomes;
}

// Why the run's ledger may not be written now, or null. Each step of its path is looked
// at without following it: one that is not there ends the walk (what is missing will be
// made); a link, a step on the way that is not a folder, a ledger that is there and not a
// regular file, or any other error in looking is a reason. So is the same file as the
// owner's ledger, as the operating system identifies files, when its identity cannot be
// read for any reason but its absence.
function ledgerProblem(root, ledgerRel, ownerRel) {
  const steps = stepsOf(root, ledgerRel);
  for (let at = 0; at < steps.length; at += 1) {
    let status;
    try {
      status = fs.lstatSync(steps[at]);
    } catch (error) {
      if (error.code === 'ENOENT') break;
      return `${ledgerRel} cannot be looked at (${error.code || error.message})`;
    }
    if (status.isSymbolicLink()) return `${ledgerRel} is reached through a link`;
    const last = at === steps.length - 1;
    if (!last && !status.isDirectory()) return `${ledgerRel} has a step that is not a folder`;
    if (last && !status.isFile()) return `${ledgerRel} is not a regular file`;
  }
  const identity = (rel) => {
    try {
      const status = fs.statSync(path.join(root, rel), { bigint: true });
      return { id: `${status.dev}:${status.ino}` };
    } catch (error) {
      return error.code === 'ENOENT' ? { id: null } : { problem: `${rel}: its identity cannot be read (${error.code || error.message})` };
    }
  };
  const ledgerId = identity(ledgerRel);
  if (ledgerId.problem !== undefined) return ledgerId.problem;
  if (ledgerId.id === null) return null;
  const ownerId = identity(ownerRel);
  if (ownerId.problem !== undefined) return ownerId.problem;
  return ownerId.id === ledgerId.id ? `${ledgerRel} is the owner's ledger` : null;
}

// Steps 1 to 14, composed: the plan on the sessions kept at step 5, the checks with their
// batches given to the site's executor (`execute`, executeBatch with the input's
// `executor` unless a test gives another), the verdicts recorded, the kept sessions
// ended, then the ledgers read again and the output made as the status command makes it,
// with `counts`. A refusal up to the recording ends every kept session before it is
// given; a refusal at step 14 comes after the recording, which stays. The providers are
// not asked again for the report. With `transcript`, every message sent to a provider and
// read from one, on every session, is kept in order, and once the run reports it is
// written there as a new file; one that cannot be is `transcript-not-written`, the
// verdicts staying recorded. A run refused before it reports writes no transcript.
async function runProject(asked, { execute, plan: planStage = planRun, waitMs, io, release } = {}) {
  const run = execute || ((batch, wait) => executeBatch(asked.executor, asked.root, batch, wait));
  const transcript = Object.hasOwn(asked, 'transcript') ? [] : null;
  const record = transcript === null ? null : (to, message) => transcript.push({ to, message });
  const { snapshot, plan, sessions } = await planStage(asked, record);
  let outcomes;
  try {
    const ends = await checkAll(sessions, plan, asked.root, run);
    outcomes = recordVerdicts(asked, sessions, snapshot, ends, { waitMs, io, release });
  } catch (failure) {
    const refusal = await afterClosing(failure, sessions);
    throw refusal;
  }
  await closeSessions(sessions);
  const counts = countsOf(plan, outcomes);
  const output = { ...reportOf(asked, rereadOf(asked, snapshot)), counts };
  if (transcript !== null) writeTranscript(asked.root, asked.transcript, transcript);
  return output;
}

// The transcript as a new file: its place judged again as at step 1, then created only if
// nothing is there (no link followed at its last step), written whole and flushed.
function writeTranscript(root, rel, messages) {
  const problem = transcriptPlaceProblem(root, rel);
  if (problem !== null) throw new Stop('transcript-not-written', `${rel} ${problem}`);
  const bytes = Buffer.from(`${JSON.stringify(messages)}\n`, 'utf8');
  let descriptor;
  try {
    descriptor = fs.openSync(path.join(root, rel), fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL);
  } catch (error) {
    throw new Stop('transcript-not-written', `${rel}: ${error.code || error.message}`);
  }
  try {
    let done = 0;
    while (done < bytes.length) {
      const wrote = fs.writeSync(descriptor, bytes, done, bytes.length - done, done);
      if (!(wrote > 0)) throw new Error(`a write made no progress (${wrote})`);
      done += wrote;
    }
    fs.fsyncSync(descriptor);
  } catch (error) {
    fs.closeSync(descriptor);
    descriptor = null;
    try {
      fs.unlinkSync(path.join(root, rel)); // the file this run created, not left half written
    } catch (ignored) {
      // gone already
    }
    throw new Stop('transcript-not-written', `${rel}: ${error.code || error.message}`);
  } finally {
    if (descriptor !== null) fs.closeSync(descriptor);
  }
}

// The bytes of standard input to `{ready: digests}`, or the refusal the command would print.
function preflightBytes(bytes) {
  try {
    return { ready: preflight(readInput(bytes)) };
  } catch (error) {
    if (error instanceof Stop) return { refused: error.reason, detail: error.detail };
    throw error;
  }
}

module.exports = {
  preflight, preflightBytes, diskName, planOf, countsOf, planRun, closeSessions, afterClosing, startCheck, exchange, SESSION_BROKE,
  checkAll, batchWait, executeBatch, recordVerdicts, runProject,
};
