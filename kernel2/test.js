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
  // A string gate other than exactly hard or soft counts as hard; a gate that is not a string changes nothing.
  assert.equal(tree.gateCountsAs('soft'), 'soft');
  assert.equal(tree.gateCountsAs('Hard'), 'hard');
  assert.equal(tree.gateCountsAs('deferred'), 'hard');
  assert.equal(tree.gateCountsAs(1), null);
  const run = (...steps) => tree.runScenario({ policy, root: { gate: 'hard' }, children: {}, steps: [{ do: { confirm: {} } }, ...steps.map((step) => ({ do: step }))] });
  assert.deepEqual(run({ edit: { node: 'root', to: 'deferred' } }).map((r) => r.status), ['open', 'open']); // already counts as hard
  assert.deepEqual(run({ edit: { node: 'root', to: 'Soft' } }).map((r) => r.status), ['open', 'open']);
  assert.deepEqual(run({ add: { child: 'k', gate: 'deferred' } }, { confirm: {} }).map((r) => r.status), ['open', 'draft', 'open']);
  assert.deepEqual(run({ add: { child: 'k', gate: null } }, { edit: { node: 'root', to: ['soft'] } }).map((r) => r.status), ['open', 'open', 'open']);
  // Starting gates follow the same rule; one that is not a string makes the scenario invalid.
  const start = (rootGate, childGate) => ({ kind: 'tree', policy, root: { gate: rootGate }, children: { k: { gate: childGate } }, steps: [{ do: { confirm: {} } }] });
  const { runScenario } = require('./scenario');
  assert.deepEqual(runScenario(start('Soft', 'deferred')).results, [{ status: 'open' }]);
  assert.deepEqual(runScenario(start('hard', 'soft')).results, [{ status: 'unguarded' }]);
  assert.throws(() => runScenario(start('hard', 1)), tree.InvalidScenario);
  assert.throws(() => runScenario(start(null, 'hard')), tree.InvalidScenario);
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

test('status: an obligation named __proto__ is kept as its own name in the report', () => {
  const { plain } = require('./plain');
  const { runScenario } = require('./scenario');
  const name = '__proto__';
  const pre = { obligation: 'sha256:a', kind: 'check', inputs: { targets: ['sha256:1'] }, provider: { name: 'p', version: '1', protocol: '0.2' } };
  const scenario = {
    kind: 'status',
    self: { writer: 'k', platform: 'p1' },
    policy: { min_hard_gates: 1, required: [], trusted_writers: [], floors: {}, attestors: {}, makes: [] },
    // A computed key: a literal `__proto__:` would set the prototype and define nothing.
    obligations: { [name]: { preimage: pre } },
    intents: { i: { owner: 'o', worker: 'w', children: [], criteria: { c: { gate: 'hard', checked_by: [name] } } } },
    steps: [{ do: { append: { kind: 'evidence', body: { obligation: name, preimage: pre, core_key: identity.identityOf(pre), platform: 'p1', verdict: 'passed', writer: 'k' } } } }],
  };
  // Written out and read back as the status command reads what it judged.
  const read = strictJson.read(JSON.stringify(scenario));
  assert.equal(read.refused, undefined);
  const last = runScenario(plain(read.value)).results.at(-1);
  assert.ok(Object.hasOwn(last.obligations, name));
  assert.equal(JSON.stringify(last.obligations), '{"__proto__":{"status":"passed"}}');
  assert.deepEqual(last.intents.i.score, { met: 1, of: 1 });
  assert.equal(last.intents.i.shown.level, 'asserted');
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

// The host: reading provider messages, the rules of a check, and a session and a check
// held with providers and an executor written here in JavaScript, so no other language
// is needed to run these tests.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { parseLine } = require('./wire');
const hostRules = require('./host-rules');
const { parseArguments } = require('./session');
const { runKey, reportEnding } = require('./check');

const sha = (text) => `sha256:${crypto.createHash('sha256').update(text).digest('hex')}`;

test('strict reading reads any depth whole, and judges depth after every other problem', () => {
  assert.deepEqual(strictJson.read('['.repeat(65) + ']'.repeat(65), { maxDepth: 64 }), { refused: 'too-deep' });
  assert.ok(strictJson.read('['.repeat(64) + ']'.repeat(64), { maxDepth: 64 }).value !== undefined);
  assert.deepEqual(strictJson.read('['.repeat(1000000) + ']'.repeat(1000000), { maxDepth: 64 }), { refused: 'too-deep' });
  assert.deepEqual(strictJson.read('['.repeat(100000), { maxDepth: 64 }), { refused: 'not-json' });
  assert.deepEqual(strictJson.read(`{"a":${'['.repeat(70)}${']'.repeat(70)},"a":1}`, { maxDepth: 64 }), { refused: 'duplicate-key' });
  assert.deepEqual(strictJson.read(`{"a":[[{"b":1.5}]]}`, { maxDepth: 64 }), { refused: 'not-an-integer' });
  assert.ok(strictJson.read('['.repeat(65) + ']'.repeat(65)).value !== undefined);
});

test('a line is read in the order the contract gives', () => {
  const line = (text) => Buffer.from(text, 'utf8');
  assert.deepEqual(parseLine(line('{"type":"x"}\r'), false), { reason: 'framing' });
  assert.deepEqual(parseLine(Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), line('{"type":"x"}')]), false), { reason: 'framing' });
  assert.deepEqual(parseLine(Buffer.from([0x7b, 0xff, 0x7d]), false), { reason: 'encoding' });
  assert.deepEqual(parseLine(line('[1]'), false), { reason: 'malformed' });
  assert.deepEqual(parseLine(line('{"type":1}'), false), { reason: 'malformed' });
  assert.deepEqual(parseLine(line('not json'), true), { reason: 'malformed' });
  assert.deepEqual(parseLine(line('{"type":"x","type":"y"}'), true), { reason: 'duplicate-key' });
  assert.deepEqual(parseLine(line('{"type":"x","n":1.0}'), true), { reason: 'not-an-integer' });
  assert.deepEqual(parseLine(line(`{"type":"x","v":${'['.repeat(64)}${']'.repeat(64)}}`), true), { reason: 'too-deep' });
  assert.deepEqual(parseLine(line('{"type":"x","b":{"c":[{"d":1,"d":2}]}}'), true), { reason: 'duplicate-key' });
  assert.deepEqual(parseLine(line('{"type":"x","n":9007199254740992}'), true), { reason: 'not-an-integer' });
  assert.deepEqual(parseLine(line('{"type":"x","s":"\\ud800"}'), true), { reason: 'encoding' });
  assert.deepEqual(parseLine(line(`{"type":"x","v":${'['.repeat(64)}${']'.repeat(64)},"type":"y"}`), true), { reason: 'duplicate-key' });
  assert.deepEqual(parseLine(line('{"type":"x","type":"y","n":1.5}'), false), { message: { type: 'y', n: 1.5 } });
  assert.deepEqual(parseLine(line('{"type":"x","n":7}'), true), { message: { type: 'x', n: 7 } });
});

const PLATFORM = { os: 'linux', arch: 'aarch64', libc: 'gnu' };
const A = { path: 'a.txt', identity: sha('a\n') };

function aCheck(changes = {}) {
  return {
    platform: PLATFORM, declared: new Set(['checker']), given: new Map([['checker', `sha256:${'c'.repeat(64)}`]]),
    inputs: new Map([['a.txt', A.identity]]), named: ['a.txt'], runs: 0,
    ceiling: { class: 'test', rank: 'bounded' }, isRegularFile: () => true, identityOf: () => null, ...changes,
  };
}

function aRun(changes = {}) {
  return {
    program: { tool: 'checker', path: 'bin/checker' }, args: ['--lib', '${tool:checker}/lib/rules.jar', 'a.txt'],
    inputs: [A], outputs: [], limits: { wall_ms: 1000, output_bytes: 1000 }, platform: PLATFORM,
    tools: [{ name: 'checker', digest: `sha256:${'c'.repeat(64)}` }], cwd: 'work', ...changes,
  };
}

test('a run that keeps every rule is accepted, and each rule refuses with its reason', () => {
  assert.equal(hostRules.runProblem(aRun(), aCheck()), null);
  assert.equal(hostRules.runProblem(aRun(), aCheck({ runs: 8 })), 'too-many-runs');
  assert.equal(hostRules.runProblem(aRun(), aCheck({ runs: 7 })), null);
  for (const broken of [{ args: 'a.txt' }, { inputs: {} }, { outputs: undefined }, { tools: [{ name: 'checker' }] }, { program: { tool: 'checker' } },
    { platform: 'linux' }, { cwd: 7 }, { limits: { wall_ms: '1' } }]) {
    assert.equal(hostRules.runProblem(aRun(broken), aCheck()), 'bad-description', JSON.stringify(broken));
  }
  assert.equal(hostRules.runProblem(null, aCheck()), 'bad-description');
  assert.equal(hostRules.runProblem(aRun({ platform: { os: 'linux', arch: 'aarch64' } }), aCheck()), 'platform-mismatch');
  assert.equal(hostRules.runProblem(aRun({ args: ['${tool:checker}/a:${tool:shell}/b'] }), aCheck()), 'undeclared-tool');
  assert.equal(hostRules.runProblem(aRun(), aCheck({ declared: new Set(['checker', 'shell']), given: new Map() })), 'tool-not-in-key');
  assert.equal(hostRules.runProblem(aRun({ tools: [{ name: 'checker', digest: 'sha256:x' }] }), aCheck()), 'tool-digest-mismatch');
  assert.equal(hostRules.runProblem(aRun({ tools: [] }), aCheck()), 'tool-not-in-run');
  assert.equal(hostRules.runProblem(aRun({ program: { tool: 'checker', path: 'bin/../x' } }), aCheck()), 'bad-path');
  assert.equal(hostRules.runProblem(aRun({ cwd: 'CON' }), aCheck()), 'bad-path');
  assert.equal(hostRules.runProblem(aRun({ args: ['-o%TEMP%', 'a.txt'] }), aCheck()), 'bad-path');
  assert.equal(hostRules.runProblem(aRun({ args: ['${tool:checker}/lib/x=/etc/passwd', 'a.txt'] }), aCheck()), 'bad-path');
  assert.equal(hostRules.runProblem(aRun({ args: ['café', 'a.txt'] }), aCheck()), 'bad-path');
  assert.equal(hostRules.runProblem(aRun({ env: { A: 'b' } }), aCheck()), 'env-not-allowed');
  assert.equal(hostRules.runProblem(aRun({ env: {} }), aCheck()), 'env-not-allowed');
  assert.equal(hostRules.runProblem(aRun({ env: null }), aCheck()), 'env-not-allowed');
  assert.equal(hostRules.runProblem(aRun({ outputs: [{ path: 'a.txt' }] }), aCheck()), 'output-overwrites-input');
  assert.equal(hostRules.runProblem(aRun({ outputs: [{ path: 'A.Txt' }] }), aCheck()), 'output-overwrites-input');
  assert.equal(hostRules.runProblem(aRun({ outputs: [{ path: 'B.TXT' }] }), aCheck({ inputs: new Map([['a.txt', A.identity], ['b.txt', A.identity]]) })), 'output-overwrites-input');
  assert.equal(hostRules.runProblem(aRun({ outputs: [{ path: 'out.txt' }] }), aCheck()), null);
  assert.equal(hostRules.runProblem(aRun({ inputs: [A, { path: 'b.txt', identity: A.identity }] }), aCheck()), 'input-not-in-key');
  assert.equal(hostRules.runProblem(aRun({ inputs: [{ path: 'a.txt', identity: sha('b') }] }), aCheck()), 'identity-mismatch');
  assert.equal(hostRules.runProblem(aRun({ args: ['a.txt\u0000x'] }), aCheck()), 'bad-arguments');
  assert.equal(hostRules.runProblem(aRun({ args: [1] }), aCheck()), 'bad-arguments');
  assert.equal(hostRules.runProblem(aRun({ args: ['-I${tool:checker}/x\u0000', 'a.txt'] }), aCheck()), 'bad-arguments');
  assert.equal(hostRules.runProblem(aRun({ inputs: [], args: [] }), aCheck()), 'missing-input');
});

test('every tool an argument names is found, with or without a file after it', () => {
  assert.deepEqual(hostRules.toolsNamed({ program: { tool: 'p' }, args: ['${tool:a}', 'x${tool:b}/f:${tool:c}/g', 7] }), ['p', 'a', 'b', 'c']);
  assert.deepEqual(hostRules.toolsNamed({ program: { tool: 'p' }, args: [] }), ['p']);
});

test('a final is checked in the contract order', () => {
  const ran = aCheck({ runs: 1 });
  const passed = { verdict: 'passed', strength: { class: 'test', rank: 'bounded' } };
  assert.equal(hostRules.finalProblem(passed, ran), null);
  assert.equal(hostRules.finalProblem({ ...passed, strength: { class: 'test', rank: 'sampled' } }, ran), null);
  assert.equal(hostRules.finalProblem('passed', ran), 'bad-final');
  assert.equal(hostRules.finalProblem({ ...passed, attachments: { path: 'e.txt' } }, ran), 'bad-final');
  assert.equal(hostRules.finalProblem({ ...passed, attachments: [{ path: 'e.txt' }] }, ran), 'bad-final');
  assert.equal(hostRules.finalProblem({ ...passed, attachments: [{ path: '../x', identity: 'sha256:0' }] }, ran), 'bad-path');
  assert.equal(hostRules.finalProblem({ ...passed, attachments: [{ path: 'e.txt', identity: 'sha256:0' }] }, aCheck({ runs: 1, isRegularFile: () => false })), 'bad-path');
  assert.equal(hostRules.finalProblem({ ...passed, attachments: [{ path: 'e.txt', identity: 'sha256:0' }] }, ran), 'identity-mismatch');
  assert.equal(hostRules.finalProblem({ ...passed, attachments: [{ path: 'e.txt', identity: 'sha256:0' }] }, aCheck({ runs: 1, identityOf: () => 'sha256:0' })), null);
  assert.equal(hostRules.finalProblem({ verdict: 'unavailable' }, ran), 'bad-verdict');
  assert.equal(hostRules.finalProblem({ verdict: 'unsupported' }, aCheck()), null);
  assert.equal(hostRules.finalProblem({ verdict: 'error' }, aCheck()), null);
  assert.equal(hostRules.finalProblem(passed, aCheck()), 'verdict-without-run');
  assert.equal(hostRules.finalProblem({ verdict: 'failed', strength: { class: 'test', rank: 'exhaustive' } }, ran), 'strength-above-ceiling');
  assert.equal(hostRules.finalProblem({ verdict: 'passed' }, ran), 'strength-above-ceiling');
  assert.equal(hostRules.finalProblem(passed, aCheck({ runs: 1, ceiling: null })), 'strength-above-ceiling');
  assert.equal(hostRules.finalProblem({ verdict: 'failed', strength: { class: 'proof', rank: 'bounded' } }, ran), 'strength-class-mismatch');
  assert.equal(hostRules.finalProblem({ verdict: 'passed', strength: { rank: 'bounded' } }, ran), 'strength-class-mismatch');
});

test('a report ends the check unless the run exited as described', () => {
  const run = aRun();
  const report = { end: 'exited', platform: PLATFORM, tools_ran: run.tools };
  assert.equal(reportEnding(report, run), null);
  assert.deepEqual(reportEnding(null, run), { outcome: 'verdict', verdict: 'error' });
  assert.deepEqual(reportEnding({ ...report, end: 'cancelled' }, run), { outcome: 'verdict', verdict: 'error' });
  assert.deepEqual(reportEnding({ ...report, end: 'unavailable' }, run), { outcome: 'verdict', verdict: 'unavailable' });
  assert.deepEqual(reportEnding({ ...report, platform: { os: 'linux', arch: 'aarch64' } }, run), { outcome: 'verdict', verdict: 'error' });
  assert.deepEqual(reportEnding({ ...report, tools_ran: [] }, run), { outcome: 'verdict', verdict: 'error' });
});

test('each run has its own key, which includes its number', () => {
  const description = aRun();
  assert.notEqual(runKey('sha256:c', 1, description), runKey('sha256:c', 2, description));
  assert.equal(runKey('sha256:c', 1, description), identity.identityOf({ check: 'sha256:c', run: 1, description: identity.identityOf(description) }));
});

test('the session command takes the limits and the provider as the contract gives them', () => {
  assert.deepEqual(parseArguments(['--deadline-ms', '5', '--max-line', '6', '--max-log', '7', '--', 'p', '--x']),
    { deadlineMs: 5, maxLine: 6, maxLog: 7, provider: ['p', '--x'] });
  assert.equal(parseArguments(['--deadline-ms', '5', '--max-line', '6', '--', 'p']), null);
  assert.equal(parseArguments(['--deadline-ms', '5', '--max-line', '6', '--max-log', '7', '--']), null);
});

// A provider and an executor in JavaScript, started with the Node that runs the tests.
const PROVIDER = `
const rl = require('node:readline').createInterface({ input: process.stdin });
const mode = process.argv[1];
const send = (m, end = '\\n') => process.stdout.write(JSON.stringify(m) + end);
let start;
rl.on('line', (text) => {
  const m = JSON.parse(text);
  if (m.type === 'hello') {
    send({ type: 'manifest', echo: m.echo, manifest: { capabilities: [{ capability: 'obligation.check', strength: { class: 'test', rank: 'bounded' } }], tools: [{ name: 'checker' }] } }, mode === 'cr' ? '\\r\\n' : '\\n');
  } else if (m.type === 'request' && m.capability === 'decision.index') {
    send({ type: 'result', id: m.id, capability: m.capability, body: { decisions: [] } });
  } else if (m.type === 'request' && m.body.op === 'start') {
    start = m.body;
    send({ type: 'result', id: m.id, capability: m.capability, body: { next: { program: { tool: 'checker', path: 'bin/c' }, args: ['a.txt'],
      inputs: start.inputs, outputs: [], limits: { wall_ms: 1000, output_bytes: 10 }, platform: start.platform,
      tools: start.tools.map((t) => ({ name: t.name, digest: t.digest })) } } });
  } else if (m.type === 'request') {
    send({ type: 'result', id: m.id, capability: m.capability, body: { final: { verdict: m.body.report.exit_status === 0 ? 'passed' : 'failed', strength: { class: 'test', rank: 'bounded' } } } });
  } else if (m.type === 'shutdown') {
    process.exit(0);
  }
});`;

const EXECUTOR = `
let text = '';
process.stdin.on('data', (d) => { text += d; });
process.stdin.on('end', () => {
  const asked = JSON.parse(text);
  process.stdout.write(JSON.stringify({ handle: 'h', end: 'exited', exit_status: Number(process.argv[1]), platform: asked.run.platform,
    isolation: 'best-effort', outputs: [], tools_ran: asked.run.tools, captured_output: { path: 'a.txt', identity: 'x' } }) + '\\n');
});`;

const KERNEL = path.join(__dirname, 'dodona-kernel2.js');

function hostSession(mode) {
  const run = spawnSync(process.execPath, [KERNEL, 'session', '--deadline-ms', '5000', '--max-line', '65536', '--max-log', '100', '--',
    process.execPath, '-e', PROVIDER, mode], { encoding: 'utf8' });
  return JSON.parse(run.stdout);
}

test('a session with a provider that keeps the protocol is ok, and one carriage return ends it', () => {
  assert.deepEqual(hostSession('well'), { outcome: 'ok', log_bytes: 0, log_truncated: false });
  assert.equal(hostSession('cr').reason, 'framing');
});

function hostCheck(exitStatus, changes = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'kernel2-check-'));
  try {
    fs.writeFileSync(path.join(root, 'a.txt'), 'a\n');
    const asked = {
      root, provider: [process.execPath, '-e', PROVIDER, 'well'], executor: [process.execPath, '-e', EXECUTOR, String(exitStatus)],
      obligation: { binding: 'b', name: 'o', kind: 'check', specified_by: ['a.txt'], targets: ['a.txt'], expect: 'holds', config: {} },
      inputs: [A], tools: [{ name: 'checker', version: '1', digest: `sha256:${'c'.repeat(64)}` }], platform: PLATFORM, deadline_ms: 5000, ...changes,
    };
    const run = spawnSync(process.execPath, [KERNEL, 'check'], { input: JSON.stringify(asked), encoding: 'utf8' });
    return JSON.parse(run.stdout);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

test('a check is taken through the provider and the executor to the provider\'s verdict', () => {
  assert.deepEqual(hostCheck(0), { outcome: 'verdict', verdict: 'passed' });
  assert.deepEqual(hostCheck(1), { outcome: 'verdict', verdict: 'failed' });
  assert.deepEqual(hostCheck(0, { inputs: [] }), { outcome: 'refused', reason: 'unknown-file' });
});

test('the host\'s own input and a checking manifest have their shapes', () => {
  const good = { root: 'r', provider: ['p'], executor: ['e'], obligation: { specified_by: ['a'], targets: [] }, inputs: [A],
    tools: [{ name: 'checker', digest: 'd' }], platform: PLATFORM, deadline_ms: 1 };
  assert.equal(hostRules.inputProblem(good), null);
  for (const broken of [{ root: 1 }, { provider: [] }, { executor: [1] }, { obligation: { specified_by: ['a'] } }, { inputs: [{ path: 'a' }] },
    { tools: [{ name: 'c' }] }, { platform: [] }, { deadline_ms: 0 }, { deadline_ms: 1.5 }]) {
    assert.equal(hostRules.inputProblem({ ...good, ...broken }), 'bad-input', JSON.stringify(broken));
  }
  const manifest = { capabilities: [{ capability: 'obligation.check', strength: { class: 'test', rank: 'bounded' } }], tools: [{ name: 'checker' }] };
  assert.equal(hostRules.manifestProblem(manifest), null);
  assert.equal(hostRules.manifestProblem({ ...manifest, capabilities: [{ capability: 'obligation.check' }] }), null);
  for (const broken of [{ capabilities: {} }, { capabilities: ['obligation.check'] }, { capabilities: [{ capability: 'x' }, { capability: 'x' }] },
    { capabilities: [{ capability: 'obligation.check', strength: { class: 'test', rank: 'certain' } }] },
    { capabilities: [{ capability: 'obligation.check', strength: { rank: 'bounded' } }] },
    { tools: ['checker'] }, { tools: [{ name: 'a/b' }] }, { tools: undefined }]) {
    assert.equal(hostRules.manifestProblem({ ...manifest, ...broken }), 'bad-manifest', JSON.stringify(broken));
  }
});

test('a report is read strictly, as one line', () => {
  const { readReport, executorWait } = require('./check');
  assert.deepEqual(readReport(Buffer.from('{"end":"exited","exit_status":0}\n')), { end: 'exited', exit_status: 0 });
  assert.equal(readReport(Buffer.from('{"end":"exited","exit_status":0.0}\n')), null);
  assert.equal(readReport(Buffer.from('{"end":"exited","end":"exited"}\n')), null);
  assert.equal(readReport(Buffer.from('{"end":"exited"}\r\n')), null);
  assert.equal(readReport(Buffer.from('{"end":"exited"}')), null);
  assert.equal(readReport(Buffer.from('\n{"end":"exited"}\n')), null);
  assert.deepEqual(readReport(Buffer.from('{"end":"exited"}\nanything after\n')), { end: 'exited' });
  assert.equal(readReport(Buffer.from('')), null);
  assert.equal(readReport(Buffer.from('[]')), null);
  assert.equal(executorWait({ limits: { wall_ms: 2147483648 } }), 24 * 60 * 60 * 1000);
  assert.equal(executorWait({ limits: { wall_ms: 1000 } }), 61000);
  assert.equal(executorWait({}), 24 * 60 * 60 * 1000);
});

test('an attachment is a regular file reached through no link', { skip: process.platform === 'win32' }, () => {
  const { isRegularFile } = require('./check');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'kernel2-attach-'));
  try {
    fs.mkdirSync(path.join(root, 'd'));
    fs.writeFileSync(path.join(root, 'd', 'f.txt'), 'x');
    fs.symlinkSync(path.join(root, 'd'), path.join(root, 'link'));
    fs.symlinkSync(path.join(root, 'd', 'f.txt'), path.join(root, 'flink'));
    assert.equal(isRegularFile(root, 'd/f.txt'), true);
    assert.equal(isRegularFile(root, 'link/f.txt'), false);
    assert.equal(isRegularFile(root, 'flink'), false);
    assert.equal(isRegularFile(root, 'd'), false);
    assert.equal(isRegularFile(root, 'missing'), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('the processes below a command are found through parents that have gone, never through a reused id', () => {
  const { below } = require('./processes');
  const e = (pid, parent, created) => ({ pid, parent, created: BigInt(created) });
  const pids = (found) => found.map((entry) => entry.pid);
  // 10 is the command, started at 100; 11 and 12 below it; 13 belongs to someone else.
  const table = [e(11, 10, 110), e(12, 11, 120), e(13, 99, 50)];
  assert.deepEqual(pids(below(table, 10, 100n, true)), [11, 12]);
  // A process created before the command cannot be below it, whatever parent id it names.
  assert.deepEqual(pids(below([e(14, 10, 90)], 10, 100n, false)), []);
  // The command has exited and its id was taken at 200 by 10': what 10' started is not the command's.
  assert.deepEqual(pids(below([e(10, 5, 200), e(11, 10, 110), e(15, 10, 210), e(16, 15, 220)], 10, 100n, true)), [11]);
});

test('the status command reads its input as one JSON object, with at most one line feed after it', () => {
  const { readInput } = require('./project-status');
  assert.deepEqual(readInput(bytes('{"a":1}')), { a: 1 });
  assert.deepEqual(readInput(bytes('{"a":1}\n')), { a: 1 });
  assert.equal(readInput(bytes('{"a":1}\n\n')), null);
  assert.equal(readInput(bytes('{"a":1}\r\n')), null);
  assert.equal(readInput(bytes('{"a":1} ')), null);
  assert.equal(readInput(bytes(' {"a":1}')), null);
  assert.equal(readInput(bytes('{"a":1,"a":2}')), null);
  assert.equal(readInput(bytes('{"a":1.5}')), null);
  assert.equal(readInput(bytes(`{"a":${'['.repeat(64)}${']'.repeat(64)}}`)), null);
  assert.deepEqual(readInput(bytes(`{"a":${'['.repeat(63)}${']'.repeat(63)}}`)).a.length, 1);
});

test('relative paths and match patterns of the status command', () => {
  const { isRelative, isPattern, segmentMatches } = require('./project-status');
  for (const ok of ['a', 'a/b.txt', '.git/x', 'a..b']) assert.equal(isRelative(ok), true, ok);
  for (const bad of ['', '/a', 'a/', 'a//b', './a', 'a/../b', 'c:x', 'a\\b', 'a\u0000b', 7]) assert.equal(isRelative(bad), false, String(bad));
  for (const ok of ['m/*.txt', 'intents/[0-9]*.md', '[---]', 'é/*']) assert.equal(isPattern(ok), true, ok);
  for (const bad of ['', '/m', 'm/../x', 'a:b', '[9-0]', '[a]', '[a-]]', 'a\\b', '[é-z]', '[a-b', 'a]']) assert.equal(isPattern(bad), false, bad);
  assert.equal(segmentMatches('*.txt', 'a.txt'), true);
  assert.equal(segmentMatches('*.txt', '.txt'), true);
  assert.equal(segmentMatches('*.txt', 'a.txt2'), false);
  assert.equal(segmentMatches('[0-9]*', '7x'), true);
  assert.equal(segmentMatches('[0-9]*', 'x7'), false);
  assert.equal(segmentMatches('a*b*c', 'aXbYbc'), true);
  assert.equal(segmentMatches('?', '?'), true);
  assert.equal(segmentMatches('*', '😀'), true);
  assert.equal(segmentMatches('[a-z]', '😀'), false);
});

test('the project file is read in the subset of TOML the contract allows', () => {
  const { readProject, Stop } = require('./project-status');
  const read = (text) => {
    try {
      return readProject(bytes(text));
    } catch (error) {
      if (error instanceof Stop) return error.reason;
      throw error;
    }
  };
  const good = '# c\n[project]\nname = "p"   # n\n\n[[binding]]\nname = "b"\nprovider = "x"\ncapabilities = [ "obligation.enumerate" ,"y" ]\nmatch = []\n';
  assert.deepEqual(read(good), [{ name: 'b', provider: 'x', capabilities: ['obligation.enumerate', 'y'], match: [] }]);
  assert.deepEqual(read('[[binding]]\n__proto__ = "z"\nname = "b"\nprovider = "x"\ncapabilities = []\n')[0].name, 'b');
  for (const bad of ['﻿[project]\n', '[project]\n[project]\n', 'name = "p"\n', '[project]\nname = "p"\nname = "q"\n', '[project]\nname = \'p\'\n',
    '[project]\nname = "a\\"b"\n', '[project]\nn = 1\n', '[project]\n name = "p"\n', '[project]\nname = "p"\r\n', '[project]\nname = "p"\t# c\n',
    '[project]\nname = "p"# c\n', '[other]\n', '[[binding]]\nname = "b"\ncapabilities = []\n', '[[binding]]\nname = "b"\nprovider = "x"\ncapabilities = "c"\n',
    '[[binding]]\nname = "b"\nprovider = "x"\ncapabilities = []\nmatch = ["a:b"]\n', '[project]\nname = "\u0085"\n', '[project]\nkey2 = "v"\n',
    '[[binding]]\nname = "b"\nprovider = "x"\ncapabilities = []\n[[binding]]\nname = "b"\nprovider = "y"\ncapabilities = []\n']) {
    assert.equal(read(bad), 'bad-project', JSON.stringify(bad));
  }
  assert.deepEqual(read('[project]\nname = "a #   b" # c  \n'), []);
});

test('coverage: where each intent tree\'s hard gates sit', () => {
  const { coverageOf } = require('./project-status');
  const intent = (gates, children = []) => ({ children, criteria: Object.fromEntries(gates.map((gate, at) => [String(at), { gate }])) });
  const intents = new Map([['r', intent(['hard', 'soft'], ['a', 'b', 'ghost'])], ['a', intent(['Hard', 'deferred'])], ['b', intent([])]]);
  const parent = new Map([['a', 'r'], ['b', 'r'], ['ghost', 'r']]);
  const coverage = coverageOf(intents, parent, 2);
  assert.deepEqual(coverage.intents.r, { own_hard: 1, subtree_hard: 2, root: 'r', tree_hard: 2, floor: 2, floor_met_only_over_tree: false });
  assert.deepEqual(coverage.intents.a, { own_hard: 1, subtree_hard: 1, root: 'r', tree_hard: 2, floor: 2, floor_met_only_over_tree: true });
  assert.deepEqual(coverage.thinnest, { r: 'b' });
});

// The run command's first slice has its own file, so that it can be run alone; this
// suite runs it too.
require('./test-run');
