'use strict';
// Unit tests for the pure functions. Run: node --test kernel2/test.js

const test = require('node:test');
const assert = require('node:assert/strict');

const strictJson = require('./strict-json');
const { canonicalize, compareUnits } = require('./canonical');
const unicode = require('./unicode');
const { checkPath, findCollisions } = require('./paths');
const evidence = require('./evidence');
const intent = require('./intent');
const plan = require('./plan');
const assurance = require('./assurance');
const tree = require('./tree');
const attempts = require('./attempts');
const platforms = require('./platforms');
const decisions = require('./decisions');
const { judgeStates } = require('./states');

const bytes = (text) => Buffer.from(text, 'utf8');

test('strict reader refuses what JSON.parse would let through', () => {
  assert.equal(strictJson.read('{"a":1,"a":2}').refused, 'duplicate-key');
  assert.equal(strictJson.read('{"a":1,"\\u0061":2}').refused, 'duplicate-key');
  assert.equal(strictJson.read('[1.0]').refused, 'not-an-integer');
  assert.equal(strictJson.read('[1e3]').refused, 'not-an-integer');
  assert.equal(strictJson.read('["\\ud83d"]').refused, 'invalid-string');
  assert.equal(strictJson.read('["\\ude00\\ud83d"]').refused, 'invalid-string');
  assert.equal(strictJson.read('[9007199254740992]').refused, 'integer-out-of-range');
  assert.equal(strictJson.read('[01]').refused, 'not-json');
  assert.equal(strictJson.read('[1,]').refused, 'not-json');
  assert.equal(strictJson.read('').refused, 'not-json');
  assert.equal(strictJson.read('[1.5, x]').refused, 'not-json'); // syntax beats the number
});

test('canonical form sorts keys by UTF-16 code units', () => {
  assert.equal(compareUnits('～', '😀') > 0, true);
  assert.equal(canonicalize('{"b":1,"a":[true,null]}').canonical, '{"a":[true,null],"b":1}');
  assert.equal(canonicalize('{"\\uff5e":1,"\\ud83d\\ude00":2}').canonical, '{"😀":2,"～":1}');
});

test('canonical strings are escaped as RFC 8785 says', () => {
  assert.equal(canonicalize('["\\u0001\\u001f\\n\\/\\u007f"]').canonical, '["\\u0001\\u001f\\n/\u007f"]');
});

test('canonical hash is the SHA-256 of the text', () => {
  assert.equal(canonicalize('{}').sha256, '44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a');
});

test('normalisation and case folding', () => {
  const codes = unicode.toCodePoints;
  assert.deepEqual(unicode.nfd(codes('é')), [0x65, 0x301]);
  assert.deepEqual(unicode.nfc(codes('é')), [0xe9]);
  assert.deepEqual(unicode.nfd(codes('한')), [0x1112, 0x1161, 0x11ab]); // Hangul by arithmetic
  assert.deepEqual(unicode.nfc([0x1112, 0x1161, 0x11ab]), [0xd55c]);
  assert.equal(unicode.isNfc('Å'), false); // singleton
  assert.equal(unicode.caselessKey('Straße'), unicode.caselessKey('STRASSE'));
  assert.notEqual(unicode.caselessKey('ı'), unicode.caselessKey('i'));
  assert.equal(unicode.isAssigned(0x378), false);
  assert.equal(unicode.isAssigned(0x41), true);
});

test('path check applies the rules in order', () => {
  const check = (text) => checkPath(bytes(text));
  assert.deepEqual(check('a/b.txt'), { accepted: true });
  assert.deepEqual(checkPath(Buffer.from([0x61, 0xff])), { refused: 'not-utf8' });
  assert.deepEqual(check(''), { refused: 'empty' });
  assert.deepEqual(check('a'.repeat(201)), { refused: 'too-long' });
  assert.deepEqual(check('a//b'), { refused: 'empty-segment' });
  assert.deepEqual(check('a/../b'), { refused: 'dot-segment' });
  assert.deepEqual(check('a'.repeat(101)), { refused: 'segment-too-long' });
  assert.deepEqual(check('a:b'), { refused: 'forbidden-character' });
  assert.deepEqual(check('a.'), { refused: 'trailing-dot-or-space' });
  assert.deepEqual(check(' a'), { refused: 'leading-space' });
  assert.deepEqual(check('Nul.txt'), { refused: 'reserved-name' });
  assert.deepEqual(check('COM²'), { refused: 'reserved-name' });
  assert.deepEqual(check('com10'), { accepted: true });
  assert.deepEqual(check('é'), { refused: 'not-nfc' });
  assert.deepEqual(check('͸'), { refused: 'unassigned-character' });
});

test('path sets collide when equal after folding', () => {
  assert.deepEqual(findCollisions(['README.md', 'readme.md', 'other']), [['README.md', 'readme.md']]);
  assert.deepEqual(findCollisions(['ı', 'i']), []);
});

test('obligation status', () => {
  const current = { definitions: { d: 'a' }, tool: 't' };
  const entry = (verdict, inputs = { d: 'a' }, tool = 't') => ({ obligation: 'o', inputs, tool, verdict });
  const judge = (records, running = [], outcomes = []) => evidence.judgeObligation('o', ['d'], current, { records, running, outcomes });
  assert.equal(judge([entry('passed')]).status, 'passed');
  assert.equal(judge([entry('failed')]).status, 'failed');
  assert.equal(judge([entry('passed'), entry('failed')]).status, 'conflict');
  assert.equal(judge([entry('passed', { d: 'b' })]).reason, 'never-run');
  assert.equal(judge([entry('passed', { d: 'a' }, 'other')]).status, 'unknown');
  assert.equal(judge([], [{ obligation: 'o', inputs: { d: 'a' }, tool: 't' }]).pending, true);
  assert.equal(judge([entry('passed')], [{ obligation: 'o', inputs: { d: 'a' }, tool: 't' }]).pending, false);
  assert.equal(judge([], [], [{ obligation: 'o', inputs: { d: 'a' }, tool: 't', outcome: 'unavailable' }]).reason, 'unavailable');
});

test('intent status and exceptions', () => {
  const policy = { exception_separation: 'apart', min_hard_gates: 1 };
  const criteria = (gate, check) => ({ c1: { gate: 'hard', check: 'passed' }, c2: { gate, check } });
  assert.equal(intent.intentStatus(policy, false, criteria('hard', 'passed')), 'draft');
  assert.equal(intent.intentStatus(policy, true, criteria('hard', 'unknown')), 'open');
  assert.equal(intent.intentStatus(policy, true, criteria('deferred', 'unknown')), 'delivered');
  assert.equal(intent.intentStatus(policy, true, criteria('deferred', 'passed')), 'fulfilled');
  assert.equal(intent.intentStatus(policy, true, { c1: { gate: 'soft', check: 'passed' } }), 'unguarded');
  assert.deepEqual(intent.judgeAmendment(policy, { by: 'owner', claims: 'cross-make', source: 'declared' }), { takes_effect: false, level: 'helper' });
  assert.deepEqual(intent.judgeAmendment(policy, { by: 'owner', claims: 'credentialed', source: 'attested' }), { takes_effect: true, level: 'cross-make' });
  assert.deepEqual(intent.judgeAmendment(policy, { by: 'worker', claims: 'apart', source: 'attested' }), { takes_effect: false, level: 'self' });
  assert.deepEqual(intent.judgeAmendment({ exception_separation: 'self' }, { by: 'owner' }), { takes_effect: true, level: 'self' });
});

test('planner follows dependencies and file identity', () => {
  const definitions = { a: { depends_on: ['b'] }, b: { depends_on: ['c'] }, c: { depends_on: [] } };
  assert.deepEqual(plan.reachable(definitions, ['a']), ['a', 'b', 'c']);
  assert.deepEqual(plan.reachable(definitions, ['c']), ['c']);
});

test('shown level is the weakest link', () => {
  assert.equal(assurance.shownLevel({ 'spec-to-code': 'proven', 'code-to-runs': 'bounded', 'runs-to-world': 'sampled' }), 'sampled');
  assert.equal(assurance.shownLevel({ 'spec-to-code': 'proven', 'code-to-runs': 'proven', 'runs-to-world': null }), 'none');
  assert.equal(assurance.nonVacuous({}), 'none-planted');
  assert.equal(assurance.nonVacuous({ a: 'passed', b: 'unknown' }), 'not-shown');
  assert.equal(assurance.nonVacuous({ a: 'passed' }), 'shown');
});

test('tree status', () => {
  const policy = { min_hard_gates: 1 };
  const node = (gate, check) => ({ gate, check });
  assert.equal(tree.treeStatus(policy, true, node('hard', 'passed'), [node('hard', 'passed')]), 'delivered');
  assert.equal(tree.treeStatus(policy, true, node('hard', 'passed'), [node('hard', 'unknown')]), 'open');
  assert.equal(tree.treeStatus(policy, true, node('hard', 'passed'), [node('soft', 'passed')]), 'open');
  assert.equal(tree.treeStatus(policy, false, node('hard', 'passed'), []), 'draft');
  assert.equal(tree.treeStatus(policy, true, node('soft', 'passed'), []), 'unguarded');
});

test('attempts: refusal then agreement is shopping', () => {
  const taken = (...states) => states.map((state) => ({ state }));
  assert.equal(attempts.overallResult([]), 'none');
  assert.equal(attempts.overallResult(taken('agreed', 'open')), 'refused');
  assert.equal(attempts.isShopped(taken('refused', 'agreed')), true);
  assert.equal(attempts.isShopped(taken('agreed', 'refused')), false);
  assert.deepEqual(attempts.judge(taken('refused', 'agreed'), 2), { result: 'refused', shopped: true, cap: 'helper', attempts: 2 });
});

test('platforms: verified claim, reproducibility', () => {
  const verdicts = { k1: { p1: 'passed', p2: 'passed' }, k2: { p1: 'passed' } };
  assert.equal(platforms.claimVerified(verdicts, ['k1', 'k2']), true);
  assert.equal(platforms.claimVerified({ k1: { p1: 'passed', p2: 'failed' } }, ['k1']), false);
  assert.equal(platforms.reproducibility(verdicts, 'k1'), 'passed');
  assert.equal(platforms.reproducibility(verdicts, 'k2'), 'unknown');
  assert.equal(platforms.reproducibility({ k: { p1: 'passed', p2: 'failed' } }, 'k'), 'failed');
});

test('decisions follow the name, not the content', () => {
  const names = new Map([['n1', 'c'], ['n2', 'a']]);
  assert.equal(decisions.isFlagged(names, 'n1', 'a'), true);
  assert.equal(decisions.isFlagged(names, 'n1', 'c'), false);
  assert.equal(decisions.isFlagged(new Map(), 'n1', 'a'), true);
});

test('states: one rule for scenarios and states', () => {
  const evidenceAnswer = judgeStates({
    kind: 'evidence',
    obligations: { o: { depends_on: ['d'] } },
    states: [{ definitions: { d: 'a' }, tool: 't', records: [], running: [{ obligation: 'o', inputs: { d: 'a' }, tool: 't' }] }],
  });
  assert.deepEqual(evidenceAnswer, { results: [{ o: { status: 'unknown', pending: true } }] });
  const intentAnswer = judgeStates({
    kind: 'intent',
    policy: { exception_separation: 'apart', min_hard_gates: 1 },
    states: [{ confirmed: true, criteria: { c: { gate: 'hard', check: 'passed' }, e: { gate: 'deferred', check: 'unknown' } }, amendments: [{ by: 'worker' }] }],
  });
  assert.deepEqual(intentAnswer, { results: [{ status: 'delivered', amendments: [{ takes_effect: false, level: 'self' }] }] });
});
