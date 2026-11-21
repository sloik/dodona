'use strict';
// The ledger file format (protocol/ledger.md): pure functions on bytes.

const crypto = require('node:crypto');
const canonical = require('./canonical');
const strictJson = require('./strict-json');

const MARKER = 'dodona1';
const LF = 0x0a;
const MAX_DEPTH = 64;

function sha256Hex(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

// The line for an entry, as bytes, and the entry's identity.
// `entry` is a plain JSON object with previous, kind and body.
function encodeEntry(entry) {
  const text = canonical.canonicalize(JSON.stringify(entry));
  if (text.refused !== undefined) throw new Error(`entry cannot be encoded: ${text.refused}`);
  const payload = Buffer.from(text.canonical, 'utf8');
  const checksum = sha256Hex(payload);
  const head = Buffer.from(`${MARKER} ${payload.length} ${checksum} `, 'utf8');
  return { line: Buffer.concat([head, payload, Buffer.from('\n')]), identity: `sha256:${checksum}` };
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// Reads one complete line (without its line feed). Returns { entry, identity } or null if it is not a good line.
// A line is exactly: dodona1, a space, the length, a space, 64 lowercase hex digits, a space, the payload.
function decodeLine(line) {
  const match = /^dodona1 (0|[1-9][0-9]*) ([0-9a-f]{64}) /.exec(line.toString('latin1'));
  if (!match) return null;
  const payload = line.subarray(match[0].length);
  if (payload.length !== Number(match[1]) || sha256Hex(payload) !== match[2]) return null;
  let payloadText;
  try {
    payloadText = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(payload);
  } catch (error) {
    return null;
  }
  if (canonical.canonicalize(payloadText).canonical !== payloadText) return null;
  // Nested no deeper than 64 levels, the entry itself the first (protocol/ledger.md, "Reading").
  if (strictJson.read(payloadText, { maxDepth: MAX_DEPTH }).refused !== undefined) return null;
  const entry = JSON.parse(payloadText);
  // An entry has exactly previous, kind and body; kind is a non-empty string.
  const shapeOk = isObject(entry) && Object.keys(entry).sort().join(',') === 'body,kind,previous'
    && typeof entry.kind === 'string' && entry.kind !== ''
    && (entry.previous === null || typeof entry.previous === 'string');
  return shapeOk ? { entry, identity: `sha256:${match[2]}` } : null;
}

// Reads a whole ledger from its bytes.
// Returns { entries, torn, keep, last } or { refused: 'corrupt', at }.
// `keep` is how many bytes are whole lines, `last` the identity of the last entry or null.
function readLedger(bytes) {
  const lastFeed = bytes.lastIndexOf(LF);
  const keep = lastFeed + 1;
  const torn = bytes.length > keep;
  const entries = [];
  let previous = null;
  let start = 0;
  for (let number = 1; start < keep; number += 1) {
    const end = bytes.indexOf(LF, start);
    const decoded = decodeLine(bytes.subarray(start, end));
    if (decoded === null || decoded.entry.previous !== previous) return { refused: 'corrupt', at: number };
    entries.push(decoded.entry);
    previous = decoded.identity;
    start = end + 1;
  }
  return { entries, torn, keep, last: previous };
}

// True if the entry nests deeper than a reader reads: more than MAX_DEPTH objects
// and arrays deep, the entry itself the first. The entry is walked one level at a
// time, without recursion, and the walk stops at the first level past the limit,
// so an entry nested to any depth is judged without running out of stack.
function tooDeep(entry) {
  let level = [entry];
  for (let depth = 1; level.length > 0; depth += 1) {
    if (depth > MAX_DEPTH) return true;
    const next = [];
    for (const value of level) {
      for (const member of Object.values(value)) {
        if (member !== null && typeof member === 'object') next.push(member);
      }
    }
    level = next;
  }
  return false;
}

module.exports = { encodeEntry, decodeLine, readLedger, tooDeep };
