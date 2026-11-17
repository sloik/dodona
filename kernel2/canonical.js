'use strict';
// The canonical encoding (protocol/canonical-encoding.md): RFC 8785 restricted
// to integers. `canonicalize` is a pure function from text to a decision.

const crypto = require('node:crypto');
const strictJson = require('./strict-json');

// Compares two strings as sequences of UTF-16 code units. JavaScript's own
// string comparison does exactly that; it is written out to make the rule visible.
function compareUnits(a, b) {
  const length = Math.min(a.length, b.length);
  for (let i = 0; i < length; i += 1) {
    const difference = a.charCodeAt(i) - b.charCodeAt(i);
    if (difference !== 0) return difference;
  }
  return a.length - b.length;
}

const SHORT_ESCAPES = { 0x08: '\\b', 0x09: '\\t', 0x0a: '\\n', 0x0c: '\\f', 0x0d: '\\r', 0x22: '\\"', 0x5c: '\\\\' };

function encodeString(text) {
  let out = '"';
  for (const character of text) {
    const code = character.codePointAt(0);
    if (SHORT_ESCAPES[code] !== undefined) out += SHORT_ESCAPES[code];
    else if (code < 0x20) out += `\\u${code.toString(16).padStart(4, '0')}`;
    else out += character;
  }
  return `${out}"`;
}

function encode(value) {
  if (value === null) return 'null';
  if (value === true) return 'true';
  if (value === false) return 'false';
  if (typeof value === 'bigint') return value.toString();
  if (typeof value === 'string') return encodeString(value);
  if (Array.isArray(value)) return `[${value.map(encode).join(',')}]`;
  const keys = [...value.keys()].sort(compareUnits);
  return `{${keys.map((key) => `${encodeString(key)}:${encode(value.get(key))}`).join(',')}}`;
}

// Returns { canonical, sha256 } or { refused }.
function canonicalize(text) {
  const read = strictJson.read(text);
  if (read.refused !== undefined) return { refused: read.refused };
  const canonical = encode(read.value);
  const sha256 = crypto.createHash('sha256').update(Buffer.from(canonical, 'utf8')).digest('hex');
  return { canonical, sha256 };
}

module.exports = { canonicalize, compareUnits, encode };
