'use strict';
// Identities of structured values, and core keys (protocol/evidence-record.schema.json).

const canonical = require('./canonical');
const strictJson = require('./strict-json');

// The identity of a plain JSON value: `sha256:` and the hash of its canonical text.
function identityOf(value) {
  const result = canonical.canonicalize(JSON.stringify(value));
  return `sha256:${result.sha256}`;
}

// The canonical text of a plain JSON value.
function canonicalText(value) {
  return canonical.canonicalize(JSON.stringify(value)).canonical;
}

const SET_FIELDS = ['specified_by', 'targets', 'closure', 'declared', 'mapping'];

// True if the list is sorted by UTF-16 code units with no repeats.
function isStrictlyIncreasing(list) {
  return list.every((item, position) => position === 0 || canonical.compareUnits(list[position - 1], item) < 0);
}

// The core key of the preimage given as JSON text.
// Returns { core_key } or { refused: reason }.
function coreKey(text) {
  const read = strictJson.read(text);
  if (read.refused !== undefined) return { refused: read.refused };
  const inputs = read.value instanceof Map ? read.value.get('inputs') : undefined;
  if (inputs instanceof Map) {
    if (inputs.has('platform')) return { refused: 'platform-in-core-key' };
    for (const field of SET_FIELDS) {
      const list = inputs.get(field);
      if (Array.isArray(list) && !isStrictlyIncreasing(list)) return { refused: 'unsorted-set' };
    }
  }
  return { core_key: `sha256:${canonical.canonicalize(text).sha256}` };
}

module.exports = { identityOf, canonicalText, coreKey, isStrictlyIncreasing };
