'use strict';
// Grading an act record: how separate was the party behind it (decision 0024,
// conformance/README.md, acts scenarios). Shared by the `acts` and `status` scenarios.

const crypto = require('node:crypto');
const { rank } = require('./intent');
const { canonicalText, isStrictlyIncreasing } = require('./identity');

const GIVEN_ROLES = ['work', 'criteria', 'brief', 'known-wrong', 'known-right'];

// The fields of the record that each fact reads.
const FACT_READS = {
  distinct: ['actor', 'worker'],
  started: ['actor', 'worker'],
  briefed: ['brief'],
  given: ['given'],
  fresh: ['fresh_context'],
  kept: ['transcript'],
  tested: ['known_bad', 'given'],
  otherMake: ['actor', 'worker'],
};

// The facts each level needs besides those of the levels below it.
const LEVEL_FACTS = {
  helper: ['distinct'],
  apart: ['started', 'briefed', 'given', 'fresh', 'kept'],
  tested: ['tested'],
  'cross-make': ['otherMake'],
};
const GRADED_LEVELS = ['helper', 'apart', 'tested', 'cross-make'];

const BOUND_FIELDS = ['kind', 'target', 'result', 'lineage'];

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isString(value) {
  return typeof value === 'string';
}

function absentOr(value, test) {
  return value === undefined || test(value);
}

// A record is malformed when a required part is missing or a present field has the wrong type.
function isMalformed(record) {
  if (!isObject(record) || !isObject(record.actor) || !isObject(record.worker)) return true;
  if (!isString(record.actor.id) || !isString(record.actor.session) || !isString(record.worker.id) || !isString(record.worker.session)) return true;
  const knownBad = record.known_bad;
  const attestation = record.attestation;
  const checks = [
    absentOr(record.brief, isObject),
    absentOr(record.given, (given) => Array.isArray(given) && given.every((item) => isObject(item) && isString(item.role) && isString(item.content))),
    absentOr(record.fresh_context, (value) => typeof value === 'boolean'),
    absentOr(record.transcript, isString),
    absentOr(knownBad, (value) => isObject(value) && isString(value.wrong) && isString(value.right) && isString(value.supplied_by)
      && typeof value.rejected_wrong === 'boolean' && typeof value.accepted_right === 'boolean'),
    absentOr(attestation, (value) => isObject(value) && isString(value.key) && isString(value.mac)
      && Array.isArray(value.covers) && value.covers.every(isString)),
    absentOr(record.kind, isString),
    absentOr(record.target, isString),
    absentOr(record.result, isString),
    absentOr(record.lineage, isObject),
  ];
  return checks.some((ok) => !ok);
}

function present(value) {
  return value !== undefined && value !== null;
}

// The name `vendor/family` of a make, or null if it does not give both.
function makeName(make) {
  if (!make || typeof make.vendor !== 'string' || typeof make.family !== 'string') return null;
  return `${make.vendor}/${make.family}`;
}

function groupOf(makes, name) {
  return makes.findIndex((group) => group.includes(name));
}

function hasItem(given, role, content) {
  return Array.isArray(given) && given.some((item) => item.role === role && item.content === content);
}

// Which facts hold, if the record is taken at its word.
function factsOf(record, policy) {
  const actor = record.actor || {};
  const worker = record.worker || {};
  const knownBad = record.known_bad;
  const actorMake = makeName(actor.make);
  const workerMake = makeName(worker.make);
  const makes = policy.makes || [];
  return {
    distinct: actor.id !== worker.id && actor.session !== worker.session,
    started: present(actor.started_by) && actor.started_by !== worker.id,
    briefed: !!record.brief && (record.brief.issued_by === 'kernel' || record.brief.issued_by === 'owner'),
    given: Array.isArray(record.given) && record.given.length > 0 && record.given.every((item) => GIVEN_ROLES.includes(item.role)),
    fresh: record.fresh_context === true,
    kept: present(record.transcript),
    tested: !!knownBad
      && (knownBad.supplied_by === 'kernel' || knownBad.supplied_by === 'owner')
      && knownBad.rejected_wrong === true
      && knownBad.accepted_right === true
      && hasItem(record.given, 'known-wrong', knownBad.wrong)
      && hasItem(record.given, 'known-right', knownBad.right),
    otherMake: actorMake !== null && workerMake !== null
      && groupOf(makes, actorMake) >= 0 && groupOf(makes, workerMake) >= 0
      && groupOf(makes, actorMake) !== groupOf(makes, workerMake),
  };
}

// The highest level the facts would support if they were all true.
function claimedLevel(facts) {
  if (!facts.distinct) return 'self';
  const apart = LEVEL_FACTS.apart.every((fact) => facts[fact]);
  if (!apart) return 'helper';
  if (!facts.tested) return 'apart';
  if (!facts.otherMake) return 'tested';
  return 'cross-make';
}

// True if the attestation names a listed key and its mac matches what it covers.
function attestationHolds(record, policy) {
  const attestation = record.attestation;
  if (!attestation || !Array.isArray(attestation.covers)) return false;
  const attestors = policy.attestors || {};
  if (!Object.hasOwn(attestors, attestation.key)) return false;
  // A key is a non-empty string of lowercase hexadecimal digits of even length.
  if (!/^([0-9a-f]{2})+$/.test(attestors[attestation.key])) return false;
  // `covers` is used as given: it must already be sorted and have no repeats.
  if (!isStrictlyIncreasing(attestation.covers)) return false;
  if (typeof attestation.mac !== 'string' || !/^[0-9a-f]{64}$/.test(attestation.mac)) return false;
  const fields = {};
  for (const name of attestation.covers) {
    if (name in record) fields[name] = record[name];
  }
  const message = canonicalText({ covers: attestation.covers, fields });
  const expected = crypto.createHmac('sha256', Buffer.from(attestors[attestation.key], 'hex')).update(message, 'utf8').digest();
  return crypto.timingSafeEqual(expected, Buffer.from(attestation.mac, 'hex'));
}

// Which facts are vouched for: every field the fact reads is covered, and the attestation holds.
function vouchedFacts(record, policy) {
  const vouched = {};
  const holds = attestationHolds(record, policy);
  // The check value must also bind what was judged: its kind, target, result and lineage.
  const binds = holds && BOUND_FIELDS.every((field) => record.attestation.covers.includes(field));
  for (const [fact, reads] of Object.entries(FACT_READS)) {
    vouched[fact] = holds && binds && reads.every((field) => record.attestation.covers.includes(field));
  }
  return vouched;
}

// Grades a record. Returns { claims, level, source }.
function gradeAct(record, policy) {
  if (isMalformed(record)) return { claims: 'self', level: 'self', source: 'declared' };
  const facts = factsOf(record, policy);
  const claims = claimedLevel(facts);
  const vouched = vouchedFacts(record, policy);
  let level = 'self';
  for (const candidate of GRADED_LEVELS) {
    if (rank(candidate) > rank(claims)) break;
    const needed = GRADED_LEVELS.slice(0, GRADED_LEVELS.indexOf(candidate) + 1).flatMap((name) => LEVEL_FACTS[name]);
    if (candidate === 'helper' || needed.every((fact) => vouched[fact])) level = candidate;
    else break;
  }
  return { claims, level, source: rank(level) > rank('helper') ? 'attested' : 'declared' };
}

function runScenario(scenario) {
  const nothing = { claims: 'self', level: 'self', source: 'declared' };
  return scenario.steps.map(({ do: step }) => {
    try {
      return gradeAct(step.grade, scenario.policy);
    } catch (error) {
      return nothing; // a record that cannot be understood earns nothing
    }
  });
}

module.exports = { isMalformed, factsOf, claimedLevel, attestationHolds, vouchedFacts, gradeAct, runScenario };
