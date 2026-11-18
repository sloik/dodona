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
const acts = require('./acts');
const status = require('./status');
const identity = require('./identity');
const ledger = require('./ledger');
const crypto = require('node:crypto');
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
  assert.equal(tree.treeStatus(policy, true, node('hard', 'passed'), [node('soft', 'passed')]), 'unguarded'); // every child needs a hard gate
  assert.equal(tree.treeStatus(policy, false, node('hard', 'passed'), []), 'draft');
  assert.equal(tree.treeStatus(policy, true, node('soft', 'passed'), []), 'unguarded');
  assert.equal(tree.treeStatus(policy, true, node('soft', 'passed'), [node('hard', 'passed')]), 'delivered');
  // The floor is counted over the whole tree, not held against each child.
  const two = { min_hard_gates: 2 };
  assert.equal(tree.treeStatus(two, true, node('hard', 'passed'), [node('hard', 'passed')]), 'delivered');
  assert.equal(tree.treeStatus(two, true, node('hard', 'passed'), []), 'unguarded');
  assert.equal(tree.treeStatus({ min_hard_gates: 0 }, true, node('soft', 'passed'), []), 'unguarded'); // below 1 is 1
  // A gate other than hard or soft in an edit or an add changes nothing.
  const run = (...steps) => tree.runScenario({ policy, root: { gate: 'hard' }, children: {}, steps: [{ do: { confirm: {} } }, ...steps.map((step) => ({ do: step }))] });
  assert.deepEqual(run({ edit: { node: 'root', to: 'deferred' } }).map((r) => r.status), ['open', 'open']);
  assert.deepEqual(run({ add: { child: 'k', gate: 'deferred' } }).map((r) => r.status), ['open', 'open']);
});

test('attempts: refusal then agreement is shopping', () => {
  const taken = (...states) => states.map((state, target) => ({ state, target: 0, ticket: String(target) }));
  assert.equal(attempts.overallResult([]), 'none');
  assert.equal(attempts.overallResult(taken('agreed', 'open')), 'refused');
  assert.equal(attempts.isShopped(taken('refused', 'agreed')), true);
  assert.equal(attempts.isShopped(taken('agreed', 'refused')), false);
  assert.deepEqual(attempts.judge(taken('refused', 'agreed'), 0, 'apart'),
    { result: 'refused', shopped: true, cap: 'helper', attempts: 2, retried: true, granted: 'helper' });
  assert.equal(attempts.grantedLevel('self', true), 'self'); // the cap never raises
});

test('attempts: a retry after a change keeps its grade up to the limit on refusals', () => {
  const taken = (...pairs) => pairs.map(([state, target], index) => ({ state, target, ticket: `t${index}` }));
  const once = taken(['refused', 0], ['agreed', 1]);
  assert.equal(attempts.notAgreed(once), 1);
  assert.deepEqual(attempts.judge(once, 1, 'apart', 2),
    { result: 'agreed', shopped: false, cap: null, attempts: 2, retried: true, granted: 'apart' });
  assert.deepEqual(attempts.judge(once, 1, 'apart', 1),
    { result: 'agreed', shopped: false, cap: 'helper', attempts: 2, retried: true, granted: 'helper' });
  const twice = taken(['refused', 0], ['refused', 1], ['agreed', 2]);
  assert.equal(attempts.judge(twice, 2, 'apart', 2).cap, 'helper');
  assert.equal(attempts.judge(twice, 2, 'apart', 3).cap, null);
  // Not retried: no cap, however many refusals.
  assert.equal(attempts.judge(taken(['refused', 0], ['refused', 1]), 1, 'apart', 1).cap, null);
  // An open attempt is not agreed and counts toward the limit.
  assert.equal(attempts.judge(taken(['open', 0], ['agreed', 1]), 1, 'apart', 1).cap, 'helper');
  assert.equal(attempts.refusalLimit({}), 2);
  assert.equal(attempts.refusalLimit({ refusals_before_cap: 3 }), 3);
  // Any other value makes the scenario invalid, refused whole and not stepped through.
  const { runScenario } = require('./scenario');
  for (const wrong of [0, -1, 1.5, '2', null, true, [2]]) {
    assert.throws(() => runScenario({ kind: 'attempts', refusals_before_cap: wrong, steps: [{ do: { take: { as: 't' } } }] }), attempts.InvalidScenario);
  }
});

test('platforms: verified claim, reproducibility', () => {
  const record = (entries) => new Map(Object.entries(entries).map(([key, byPlatform]) => [key,
    new Map(Object.entries(byPlatform).map(([platform, verdicts]) => [platform, new Set(verdicts)]))]));
  const recorded = record({ k1: { p1: ['passed'], p2: ['passed'] }, k2: { p1: ['passed'] } });
  assert.equal(platforms.claimVerified(recorded, 'k1'), true);
  assert.equal(platforms.claimVerified(recorded, 'k2'), false); // another key agreeing verifies nothing
  assert.equal(platforms.claimVerified(record({ k1: { p1: ['passed'], p2: ['failed'] } }), 'k1'), false);
  assert.equal(platforms.claimVerified(record({ k1: { p1: ['failed'], p2: ['failed'] } }), 'k1'), true);
  assert.equal(platforms.claimVerified(record({ k1: { p1: ['passed', 'failed'], p2: ['passed'], p3: ['passed'] } }), 'k1'), false);
  // A disagreement on one key does not void another key's claim.
  assert.equal(platforms.claimVerified(record({ k1: { p1: ['passed'], p2: ['passed'] }, k2: { p1: ['passed'], p2: ['failed'] } }), 'k1'), true);
  assert.equal(platforms.reproducibility(recorded, 'k1'), 'agrees');
  assert.equal(platforms.reproducibility(recorded, 'k2'), 'unknown');
  assert.equal(platforms.reproducibility(record({ k: { p1: ['passed', 'failed'] } }), 'k'), 'differs');
});

test('decisions follow the names, not the content', () => {
  const names = new Map([['n1', 'c'], ['n2', 'a']]);
  assert.equal(decisions.isFlagged(names, ['n1'], new Map([['n1', 'a']])), true);
  assert.equal(decisions.isFlagged(names, ['n1'], new Map([['n1', 'c']])), false);
  assert.equal(decisions.isFlagged(names, ['n1', 'n2'], new Map([['n1', 'c'], ['n2', 'b']])), true);
  assert.equal(decisions.isFlagged(new Map(), ['n1'], new Map([['n1', 'a']])), true);
});

const KEY = '6b65792d666f722d7468652d6b69742d6f6e6c792d6e6f742d612d736563726574';
const policy = { attestors: { h: KEY }, makes: [['a/x'], ['b/y']] };
const record = () => ({
  ticket: 't', kind: 'match-check', target: 'sha256:00',
  actor: { id: 'c', session: 's2', started_by: 'h', make: { vendor: 'b', family: 'y' } },
  worker: { id: 'w', session: 's1', make: { vendor: 'a', family: 'x' } },
  brief: { issued_by: 'kernel', content: 'sha256:01' },
  given: [{ role: 'work', content: 'sha256:02' }],
  fresh_context: true,
  transcript: 'sha256:03',
});
const attest = (rec, covers) => {
  const fields = {};
  for (const name of covers) fields[name] = rec[name];
  const mac = crypto.createHmac('sha256', Buffer.from(KEY, 'hex')).update(canonicalize(JSON.stringify({ covers, fields })).canonical).digest('hex');
  return { ...rec, attestation: { harness: 'h', key: 'h', covers, mac } };
};
const ALL = ['actor', 'worker', 'brief', 'given', 'fresh_context', 'transcript'];

test('acts: a claim alone earns helper, a vouched record earns its level', () => {
  assert.deepEqual(acts.gradeAct(record(), policy), { claims: 'apart', level: 'helper', source: 'declared' });
  assert.deepEqual(acts.gradeAct(attest(record(), ALL), policy), { claims: 'apart', level: 'helper', source: 'declared' }); // does not bind what was judged
  const bound = { ...record(), kind: 'match-check', result: 'agreed', lineage: { intent: 'i', kind: 'match-check' } };
  assert.deepEqual(acts.gradeAct(attest(bound, [...ALL, 'kind', 'lineage', 'result', 'target', 'ticket'].sort()), policy), { claims: 'apart', level: 'apart', source: 'attested' });
});

test('acts: a bad mac, an unlisted key or an uncovered field vouches for nothing', () => {
  const good = attest(record(), ALL);
  assert.equal(acts.gradeAct({ ...good, attestation: { ...good.attestation, mac: '0'.repeat(64) } }, policy).level, 'helper');
  assert.equal(acts.gradeAct({ ...good, attestation: { ...good.attestation, key: 'other' } }, policy).level, 'helper');
  assert.equal(acts.gradeAct(attest(record(), ALL.filter((name) => name !== 'transcript')), policy).level, 'helper');
});

test('acts: the worker is never separate, a missing started_by is not "started"', () => {
  const same = record();
  same.actor.id = 'w';
  assert.equal(acts.gradeAct(same, policy).claims, 'self');
  const unstarted = record();
  delete unstarted.actor.started_by;
  assert.equal(acts.gradeAct(unstarted, policy).claims, 'helper');
});

test('acts: tested needs the known items among given', () => {
  const rec = record();
  rec.known_bad = { wrong: 'sha256:w', right: 'sha256:r', supplied_by: 'owner', criterion: 'c', rejected_wrong: true, accepted_right: true };
  assert.equal(acts.factsOf(rec, policy).tested, false);
  rec.given.push({ role: 'known-wrong', content: 'sha256:w' }, { role: 'known-right', content: 'sha256:r' });
  assert.equal(acts.factsOf(rec, policy).tested, true);
  assert.equal(acts.claimedLevel(acts.factsOf(rec, policy)), 'cross-make');
});

test('core keys: sets must be sorted, the platform stays out', () => {
  const preimage = (inputs) => JSON.stringify({ obligation: 'sha256:a', kind: 'check', inputs, provider: { name: 'p', version: '1', protocol: '0.2' } });
  assert.equal(identity.coreKey(preimage({ targets: ['sha256:a', 'sha256:b'] })).core_key.startsWith('sha256:'), true);
  assert.deepEqual(identity.coreKey(preimage({ targets: ['sha256:b', 'sha256:a'] })), { refused: 'unsorted-set' });
  assert.deepEqual(identity.coreKey(preimage({ closure: ['sha256:a', 'sha256:a'] })), { refused: 'unsorted-set' });
  assert.deepEqual(identity.coreKey(preimage({ platform: {} })), { refused: 'platform-in-core-key' });
});

test('status: baseline and pairing targets are identities of their objects', () => {
  const intent = { owner: 'o', worker: 'w', children: ['b', 'a'], criteria: { c: { gate: 'hard', checked_by: ['y', 'x'] } } };
  const same = { ...intent, children: ['a', 'b'], criteria: { c: { gate: 'hard', checked_by: ['x', 'y'] } } };
  assert.equal(status.baselineOf(intent), status.baselineOf(same));
  assert.notEqual(status.baselineOf(intent), status.baselineOf({ ...intent, owner: 'p' }));
  assert.equal(status.pairingTarget('i', 'c', 'o'), identity.identityOf({ intent: 'i', criterion: 'c', obligation: 'o' }));
});

test('ledger: entries chain, a torn tail is dropped, damage is refused with a line number', () => {
  const first = ledger.encodeEntry({ previous: null, kind: 'evidence', body: { n: 1 } });
  const second = ledger.encodeEntry({ previous: first.identity, kind: 'act', body: { n: 2 } });
  const whole = Buffer.concat([first.line, second.line]);
  const read = ledger.readLedger(whole);
  assert.equal(read.entries.length, 2);
  assert.equal(read.torn, false);
  const torn = ledger.readLedger(whole.subarray(0, whole.length - 5));
  assert.equal(torn.entries.length, 1);
  assert.equal(torn.torn, true);
  assert.deepEqual(ledger.readLedger(Buffer.concat([second.line, first.line])), { refused: 'corrupt', at: 1 });
  assert.deepEqual(ledger.readLedger(Buffer.concat([first.line, Buffer.from('junk\n')])), { refused: 'corrupt', at: 2 });
  assert.equal(ledger.readLedger(Buffer.alloc(0)).entries.length, 0);
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

test('status: the level shown is the weakest criterion, an exception counts only from the owner at the floor', () => {
  const pre = (target) => ({ obligation: 'sha256:a', kind: 'check', inputs: { targets: [target] }, provider: { name: 'p', version: '1', protocol: '0.2' } });
  const self = { writer: 'k', platform: 'p1' };
  const evidenceBody = (name, preimage, extra) => ({
    obligation: name, preimage, core_key: identity.identityOf(preimage), platform: 'p1', verdict: 'passed', writer: 'k', ...extra,
  });
  const scenario = {
    self,
    policy: { min_hard_gates: 1, required: [], trusted_writers: [], floors: { 'grant-amendment': 'helper' }, attestors: {}, makes: [] },
    obligations: { a: { preimage: pre('sha256:1') }, b: { preimage: pre('sha256:2') } },
    intents: { i: { owner: 'o', worker: 'w', children: [], criteria: { c1: { gate: 'hard', checked_by: ['a'] }, c2: { gate: 'soft', checked_by: ['b'] } } } },
    steps: [
      { do: { append: { kind: 'evidence', body: evidenceBody('a', pre('sha256:1'), { level: 'proven' }) } } },
      { do: { append: { kind: 'evidence', body: evidenceBody('b', pre('sha256:2'), { level: 'bounded' }) } } },
      { do: { append: { kind: 'evidence', body: evidenceBody('b', pre('sha256:2'), {}) } } },
    ],
  };
  const results = status.runScenario(scenario);
  assert.deepEqual(results[0].intents.i.shown, { level: 'none', criterion: 'c2' });
  assert.deepEqual(results[1].intents.i.shown, { level: 'bounded', criterion: 'c2' });
  assert.deepEqual(results[2].intents.i.shown, { level: 'bounded', criterion: 'c2' }); // the strongest record counts
  assert.deepEqual(results[2].intents.i.exceptions, { counted: 0, below_floor: 0 });
});

test('the safety net does not fire on any scenario of the kit', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const { runScenario } = require('./scenario');
  const written = [];
  const original = process.stderr.write;
  process.stderr.write = (text) => { written.push(String(text)); return true; };
  let count = 0;
  try {
    const base = path.join(process.env.DODONA_ROOT || path.join(__dirname, '..'), 'conformance', 'kernel');
    for (const kind of fs.readdirSync(base)) {
      if (!fs.statSync(path.join(base, kind)).isDirectory()) continue;
      for (const file of fs.readdirSync(path.join(base, kind))) {
        const scenario = JSON.parse(fs.readFileSync(path.join(base, kind, file), 'utf8'));
        // Give the kernel only what the judge gives it: each step's `do`, not what is expected.
        runScenario({ ...scenario, steps: scenario.steps.map((step) => ({ do: step.do })) });
        count += 1;
      }
    }
  } finally {
    process.stderr.write = original;
  }
  assert.ok(count > 90);
  assert.deepEqual(written, []);
});

test('the safety net fires, and says so, when a step throws', () => {
  const { runScenario } = require('./scenario');
  const written = [];
  const original = process.stderr.write;
  process.stderr.write = (text) => { written.push(String(text)); return true; };
  try {
    const poisoned = { get criterion() { throw new Error('boom'); }, to: 'soft' };
    const result = runScenario({ kind: 'intent', policy: { exception_separation: 'self', min_hard_gates: 1 },
      criteria: { c: { gate: 'hard' } }, steps: [{ do: { confirm: {} } }, { do: { edit: poisoned } }] });
    assert.equal(result.results.length, 2);
  } finally {
    process.stderr.write = original;
  }
  assert.ok(written.length > 0);
});

test('acts: a malformed record is self; the check value must bind what was judged', () => {
  assert.equal(acts.isMalformed({ actor: { id: 'a', session: 's' }, worker: { id: 'w' } }), true); // no worker session
  assert.equal(acts.isMalformed({ ...record(), fresh_context: 'yes' }), true);
  assert.equal(acts.isMalformed({ ...record(), brief: { issued_by: 'other', content: 'x' }, given: [{ role: 'other', content: 'x' }] }), false);
  assert.deepEqual(acts.gradeAct({ ...record(), transcript: 7 }, policy), { claims: 'self', level: 'self', source: 'declared' });
  const unbound = attest(record(), ALL); // covers the facts' fields but not kind, target, result, lineage
  assert.equal(acts.gradeAct(unbound, policy).level, 'helper');
  const bound = attest(record(), [...ALL, 'kind', 'lineage', 'result', 'target', 'ticket'].sort());
  assert.equal(acts.gradeAct({ ...bound, lineage: { intent: 'i', kind: 'match-check' } }, policy).level, 'helper'); // lineage not in the record when signed
});

test('acts: a key that is not even-length lowercase hex names no key; covers must be sorted', () => {
  const cover = [...ALL, 'kind', 'lineage', 'result', 'target', 'ticket'].sort();
  const rec = { ...record(), kind: 'match-check', result: 'agreed', lineage: { intent: 'i', kind: 'match-check' } };
  const good = attest(rec, cover);
  assert.equal(acts.gradeAct(good, policy).level, 'apart');
  assert.equal(acts.gradeAct(good, { ...policy, attestors: { h: 'ABCD' } }).level, 'helper');
  assert.equal(acts.gradeAct(good, { ...policy, attestors: { h: '' } }).level, 'helper');
  const shuffled = attest(rec, [...cover].reverse());
  assert.equal(acts.gradeAct(shuffled, policy).level, 'helper');
});

test('ledger: strict lines, any non-empty kind, no partial reads', () => {
  const first = ledger.encodeEntry({ previous: null, kind: 'note', body: { n: 1 } });
  assert.equal(ledger.readLedger(first.line).entries[0].kind, 'note');
  const text = first.line.toString('utf8');
  assert.deepEqual(ledger.readLedger(Buffer.from(text.replace('dodona1 ', 'dodona1  '))), { refused: 'corrupt', at: 1 });
  assert.deepEqual(ledger.readLedger(Buffer.from(text.replace('dodona1 ', 'dodona2 '))), { refused: 'corrupt', at: 1 });
  assert.deepEqual(ledger.readLedger(Buffer.from(text.replace(/ (\d+) /, (match, length) => ` 0${length} `))), { refused: 'corrupt', at: 1 });
  assert.deepEqual(ledger.readLedger(Buffer.from('\n')), { refused: 'corrupt', at: 1 });
  assert.deepEqual(ledger.readLedger(Buffer.from(`${text.replace(/[0-9a-f]{64}/, (digest) => digest.toUpperCase())}`)), { refused: 'corrupt', at: 1 });
  const nullPayload = Buffer.from(`dodona1 4 ${crypto.createHash('sha256').update('null').digest('hex')} null\n`);
  assert.deepEqual(ledger.readLedger(nullPayload), { refused: 'corrupt', at: 1 });
});

test('core keys: every set, unknown fields and a platform anywhere', () => {
  const preimage = (top, inputs) => JSON.stringify({ obligation: 'sha256:a', kind: 'check', inputs, provider: { name: 'p', version: '1', protocol: '0.2' }, ...top });
  assert.deepEqual(identity.coreKey(preimage({}, { declared: ['sha256:b', 'sha256:a'] })), { refused: 'unsorted-set' });
  assert.deepEqual(identity.coreKey(preimage({}, { mapping: ['sha256:a', 'sha256:a'] })), { refused: 'unsorted-set' });
  assert.deepEqual(identity.coreKey(preimage({ platform: null }, {})), { refused: 'platform-in-core-key' });
  assert.deepEqual(identity.coreKey(preimage({ surprise: 1 }, {})), { refused: 'unknown-field' });
});

test('a step with a value of the wrong type changes nothing', () => {
  const { runScenario } = require('./scenario');
  const same = (kind, scenario, good, bad) => {
    const a = runScenario({ kind, ...scenario, steps: [{ do: good }] }).results;
    const b = runScenario({ kind, ...scenario, steps: [{ do: good }, { do: bad }] }).results;
    assert.deepEqual(b[1].plan === undefined ? b[1] : { plan: b[1].plan }, a[0].plan === undefined ? a[0] : { plan: a[0].plan });
  };
  same('attempts', {}, { take: { as: 't1' } }, { take: { as: 0 } });
  same('plan', { granularity: 'definition', definitions: { d: { depends_on: [], file: 'f' } }, obligations: { o: { targets: ['d'] } }, start: { content: { d: 'a' }, tools: {} } },
    { run: { obligation: 'o' } }, { edit: { definition: 'd', to: -1 } });
  const evidence = { obligations: { o: { depends_on: ['d'] } }, start: { definitions: { d: 'a' }, tool: 't', backend: 'up' } };
  same('evidence', evidence, { submit: { obligation: 'o', as: 'j' } }, { submit: { obligation: 'o', as: false } });
  same('evidence', evidence, { submit: { obligation: 'o', as: 'j' } }, { edit: { definition: 'd', to: true } });
});

test('status: an evidence entry with a wrongly typed field is not a record and is not rejected', () => {
  const pre = { obligation: 'sha256:a', kind: 'check', inputs: { targets: ['sha256:1'] }, provider: { name: 'p', version: '1', protocol: '0.2' } };
  const body = (extra) => ({ obligation: 'a', preimage: pre, core_key: 'sha256:wrong', platform: 'p1', verdict: 'passed', writer: 'k', ...extra });
  const scenario = (entry) => ({ self: { writer: 'k', platform: 'p1' }, policy: { min_hard_gates: 1, required: [], trusted_writers: [], floors: {}, attestors: {}, makes: [] },
    obligations: { a: { preimage: pre } }, intents: {}, steps: [{ do: { append: { kind: 'evidence', body: entry } } }] });
  assert.equal(status.runScenario(scenario(body({}))).at(-1).rejected, 1);
  for (const wrong of [{ platform: true }, { writer: 0 }, { obligation: [] }, { core_key: null }, { preimage: 'x' }]) {
    assert.equal(status.runScenario(scenario(body(wrong))).at(-1).rejected, 0);
  }
});

test('evidence: the reason is the attempt asked for last, not the one that ended last', () => {
  const steps = [
    { submit: { obligation: 'o', as: 'j1' } }, { backend: { to: 'down' } }, { submit: { obligation: 'o', as: 'j2' } },
    { lose: { run: 'j1' } }, { backend: { to: 'up' } }, { submit: { obligation: 'o', as: 'j3' } }, { lose: { run: 'j3' } },
  ];
  const scenario = { obligations: { o: { depends_on: ['d'] } }, start: { definitions: { d: 'a' }, tool: 't', backend: 'up' }, steps: steps.map((step) => ({ do: step })) };
  assert.deepEqual(evidence.runScenario(scenario).map((result) => result.o.reason),
    ['pending', 'pending', 'pending', 'unavailable', 'unavailable', 'pending', 'error']);
});
