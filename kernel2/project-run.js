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
  answerProblem, runKey, isRegularFile, fileIdentity, namedFiles,
} = require('./check');
const {
  readInput, isRelative, checkInput, isDirectory, fileId, stepsOf, snapshotOf, endSession, Stop,
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
async function planRun(asked) {
  const digests = preflight(asked);
  const sessions = [];
  try {
    const snapshot = await snapshotOf(asked, digests, sessions);
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
};
