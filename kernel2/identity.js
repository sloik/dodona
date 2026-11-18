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
const TOP_FIELDS = ['obligation', 'kind', 'inputs', 'provider'];
const INPUT_FIELDS = ['specified_by', 'targets', 'closure', 'artifacts', 'tools', 'config', 'declared', 'expect', 'mapping'];
const PROVIDER_FIELDS = ['name', 'version', 'protocol'];

// True if the list is sorted by UTF-16 code units with no repeats.
function isStrictlyIncreasing(list) {
  return list.every((item, position) => position === 0 || canonical.compareUnits(list[position - 1], item) < 0);
}

// True if a map has a field the definition does not have. Names starting `x-` are extensions.
function hasUnknownField(map, allowed) {
  return [...map.keys()].some((key) => !allowed.includes(key) && !key.startsWith('x-'));
}

// The core key of the preimage given as JSON text.
// Returns { core_key } or { refused: reason }.
function coreKey(text) {
  const read = strictJson.read(text);
  if (read.refused !== undefined) return { refused: read.refused };
  const preimage = read.value;
  if (!(preimage instanceof Map)) return { refused: 'unknown-field' };
  const inputs = preimage.get('inputs');
  const provider = preimage.get('provider');
  if (preimage.has('platform') || (inputs instanceof Map && inputs.has('platform'))) return { refused: 'platform-in-core-key' };
  if (hasUnknownField(preimage, TOP_FIELDS)
    || (inputs instanceof Map && hasUnknownField(inputs, INPUT_FIELDS))
    || (provider instanceof Map && hasUnknownField(provider, PROVIDER_FIELDS))) return { refused: 'unknown-field' };
  if (inputs instanceof Map) {
    for (const field of SET_FIELDS) {
      const list = inputs.get(field);
      if (Array.isArray(list) && !isStrictlyIncreasing(list)) return { refused: 'unsorted-set' };
    }
  }
  return { core_key: `sha256:${canonical.canonicalize(text).sha256}` };
}

module.exports = { identityOf, canonicalText, coreKey, isStrictlyIncreasing };
