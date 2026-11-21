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
const {
  readInput, isRelative, checkInput, isDirectory, fileId, stepsOf, snapshotOf, Stop,
} = require('./project-status');

// The statuses that are a current result: reused, nothing sent for them.
const CURRENT = ['passed', 'failed', 'conflict'];
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

// Steps 1 to 10. The providers are asked as the status command asks them, each session
// closed after its answer: holding a checking binding's session open for the checks
// (step 5 of the run) is a later part, as are steps 11 to 14.
async function planRun(asked) {
  const digests = preflight(asked);
  const snapshot = await snapshotOf(asked, digests);
  return { digests, snapshot, plan: planOf(snapshot) };
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

module.exports = { preflight, preflightBytes, diskName, planOf, countsOf, planRun };
