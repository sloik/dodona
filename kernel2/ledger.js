'use strict';
// The ledger file format (protocol/ledger.md): pure functions on bytes.

const crypto = require('node:crypto');
const canonical = require('./canonical');

const MARKER = 'dodona1';
const KINDS = ['evidence', 'act', 'submission', 'outcome'];
const LF = 0x0a;

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

// Reads one complete line (without its line feed). Returns { entry, identity } or null if it is not a good line.
function decodeLine(line) {
  const text = new TextDecoder('utf-8', { fatal: false, ignoreBOM: true }).decode(line);
  const match = /^dodona1 (0|[1-9][0-9]*) ([0-9a-f]{64}) /.exec(text);
  if (!match) return null;
  const headBytes = Buffer.byteLength(match[0], 'utf8');
  const payload = line.subarray(headBytes);
  if (payload.length !== Number(match[1]) || sha256Hex(payload) !== match[2]) return null;
  let payloadText;
  try {
    payloadText = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(payload);
  } catch (error) {
    return null;
  }
  const again = canonical.canonicalize(payloadText);
  if (again.canonical !== payloadText) return null;
  const entry = JSON.parse(payloadText);
  const keys = Object.keys(entry).sort().join(',');
  const shapeOk = entry !== null && typeof entry === 'object' && !Array.isArray(entry) && keys === 'body,kind,previous'
    && KINDS.includes(entry.kind) && (entry.previous === null || typeof entry.previous === 'string');
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

module.exports = { encodeEntry, decodeLine, readLedger };
