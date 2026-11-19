'use strict';
// Reading and writing provider messages (protocol/README.md, "Framing";
// conformance/README.md, "Reading" and "Reading in a check").
//
// One message per line, ended by a single line feed. A line is checked, in this
// order: longer than the limit is `too-long` (found while it arrives, so it is never
// held whole); a carriage return before the line feed or a byte-order mark is
// `framing`; bytes that are not UTF-8 are `encoding`; text that is not one JSON
// object with a string `type` is `malformed`. Read strictly, as in a check, a
// repeated key is `duplicate-key`, a number with a fraction or exponent is
// `not-an-integer`, and nesting deeper than 64 is `too-deep`. The provider closing
// its output is `closed`; a wait that outlasts its deadline is `deadline`.
//
// Standard error is read all the time; only the first `maxLog` bytes are kept.

const strictJson = require('./strict-json');
const { plain } = require('./plain');

const MAX_DEPTH = 64;
const BOM = Buffer.from([0xef, 0xbb, 0xbf]);

// What a strict reading refuses, as a reason a host reports. A lone surrogate and an
// integer out of range are named by no rule; they make the message not one message.
const STRICT_REASONS = { 'not-json': 'malformed', 'duplicate-key': 'duplicate-key', 'not-an-integer': 'not-an-integer', 'too-deep': 'too-deep' };

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

// One complete line, without its line feed, to { message } or { reason }.
function parseLine(line, strict) {
  if (line.length > 0 && line[line.length - 1] === 0x0d) return { reason: 'framing' };
  if (line.subarray(0, 3).equals(BOM)) return { reason: 'framing' };
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(line);
  } catch (error) {
    return { reason: 'encoding' };
  }
  let message;
  if (strict) {
    const read = strictJson.read(text, { maxDepth: MAX_DEPTH });
    if (read.refused !== undefined) return { reason: STRICT_REASONS[read.refused] || 'malformed' };
    if (!(read.value instanceof Map)) return { reason: 'malformed' };
    message = plain(read.value);
  } else {
    try {
      message = JSON.parse(text);
    } catch (error) {
      return { reason: 'malformed' };
    }
  }
  if (!isObject(message) || typeof message.type !== 'string') return { reason: 'malformed' };
  return { message };
}

class Wire {
  constructor(child, { maxLine, maxLog, strict }) {
    this.child = child;
    this.maxLine = maxLine;
    this.maxLog = maxLog;
    this.strict = strict;
    this.partial = [];
    this.partialBytes = 0;
    this.items = []; // complete lines, or { reason } for a line found too long
    this.stopped = false; // after a line too long nothing more is taken
    this.ended = false;
    this.closed = false;
    this.waiters = [];
    this.log = [];
    this.logKept = 0;
    this.logBytes = 0;
    child.stdout.on('data', (data) => this.take(data));
    child.stdout.on('end', () => {
      this.ended = true;
      this.wake();
    });
    child.stdout.on('close', () => {
      this.ended = true;
      this.wake();
    });
    child.stderr.on('data', (data) => this.keepLog(data));
  }

  keepLog(data) {
    this.logBytes += data.length;
    const room = this.maxLog - this.logKept;
    if (room > 0) {
      const kept = data.subarray(0, room);
      this.log.push(kept);
      this.logKept += kept.length;
    }
  }

  take(data) {
    if (this.stopped) return;
    let from = 0;
    while (from < data.length) {
      const end = data.indexOf(0x0a, from);
      const piece = data.subarray(from, end === -1 ? data.length : end);
      if (this.partialBytes + piece.length > this.maxLine) {
        this.items.push({ reason: 'too-long' });
        this.stopped = true;
        this.partial = [];
        this.partialBytes = 0;
        break;
      }
      if (end === -1) {
        this.partial.push(piece);
        this.partialBytes += piece.length;
        break;
      }
      this.items.push({ line: Buffer.concat([...this.partial, piece]) });
      this.partial = [];
      this.partialBytes = 0;
      from = end + 1;
    }
    this.wake();
  }

  wake() {
    const waiters = this.waiters;
    this.waiters = [];
    for (const resolve of waiters) resolve();
  }

  // Resolves at the next change, or at `until` (a performance.now() time), whichever is first.
  change(until) {
    return new Promise((resolve) => {
      const timer = setTimeout(resolve, Math.max(0, until - performance.now()));
      this.waiters.push(() => {
        clearTimeout(timer);
        resolve();
      });
    });
  }

  // The next message, to { message } or { reason }. `until` is a performance.now() time.
  async next(until) {
    for (;;) {
      if (this.items.length > 0) {
        const item = this.items.shift();
        return item.reason !== undefined ? { reason: item.reason } : parseLine(item.line, this.strict);
      }
      if (this.ended) return { reason: 'closed' };
      if (performance.now() >= until) return { reason: 'deadline' };
      await this.change(until);
    }
  }

  // True when the provider has written anything not yet read.
  hasMore() {
    return this.items.length > 0 || this.partialBytes > 0;
  }

  send(message) {
    if (this.closed) return;
    try {
      this.child.stdin.write(`${JSON.stringify(message)}\n`);
    } catch (error) {
      // the provider has gone; reading will say so
    }
  }

  close() {
    this.closed = true;
    try {
      this.child.stdin.end();
    } catch (error) {
      // already closed
    }
  }

  logSummary() {
    return { log_bytes: this.logBytes, log_truncated: this.logBytes > this.maxLog };
  }
}

module.exports = { Wire, parseLine, isObject, MAX_DEPTH };
