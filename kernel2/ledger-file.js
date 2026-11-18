'use strict';
// The ledger on disk (protocol/ledger.md, "Appending"): lock, read, cut a torn
// tail, write, flush to disk, unlock. Works the same on macOS, Linux and Windows.

const fs = require('node:fs');
const ledger = require('./ledger');

// Errors that mean "the lock is held (or Windows is busy with it)", so try again.
const BUSY = ['EEXIST', 'EPERM', 'EACCES', 'EBUSY'];

function pause(milliseconds) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
}

// Creates the lock file exclusively, retrying until `waitMs` has passed.
// Returns an open descriptor, or null if the lock stayed held.
function takeLock(lockPath, waitMs) {
  const deadline = Date.now() + waitMs;
  for (;;) {
    try {
      return fs.openSync(lockPath, 'wx');
    } catch (error) {
      if (!BUSY.includes(error.code)) throw error;
    }
    if (Date.now() >= deadline) return null;
    pause(5);
  }
}

// Removes the lock file. Windows may briefly refuse, so try a few times.
function releaseLock(descriptor, lockPath) {
  fs.closeSync(descriptor);
  for (let attempt = 0; ; attempt += 1) {
    try {
      fs.unlinkSync(lockPath);
      return;
    } catch (error) {
      if (attempt >= 50 || !BUSY.includes(error.code)) throw error;
      pause(10);
    }
  }
}

function readBytes(path) {
  try {
    return fs.readFileSync(path);
  } catch (error) {
    if (error.code === 'ENOENT') return Buffer.alloc(0);
    throw error;
  }
}

function syncedWrite(path, flag, bytes, truncateTo) {
  const descriptor = fs.openSync(path, flag);
  try {
    if (truncateTo !== undefined) fs.ftruncateSync(descriptor, truncateTo);
    if (bytes) fs.writeSync(descriptor, bytes, 0, bytes.length, truncateTo === undefined ? null : truncateTo);
    fs.fsyncSync(descriptor);
  } finally {
    fs.closeSync(descriptor);
  }
}

// { ledger, kind, body, wait_ms } to { appended } or { refused: locked, corrupt or bad-request }.
function append(request) {
  // A request with no string kind, no body, or no ledger name is refused and writes nothing.
  if (typeof request.kind !== 'string' || request.kind === '' || request.body === undefined || typeof request.ledger !== 'string') {
    return { refused: 'bad-request' };
  }
  try {
    ledger.encodeEntry({ previous: null, kind: request.kind, body: request.body });
  } catch (error) {
    return { refused: 'bad-request' };
  }
  const path = request.ledger;
  const waitMs = Number(request.wait_ms) || 0;
  const lockPath = `${path}.lock`;
  const lock = takeLock(lockPath, waitMs);
  if (lock === null) return { refused: 'locked' };
  try {
    const read = ledger.readLedger(readBytes(path));
    if (read.refused) return { refused: 'corrupt' };
    const entry = ledger.encodeEntry({ previous: read.last, kind: request.kind, body: request.body });
    if (read.torn) syncedWrite(path, 'r+', null, read.keep);
    syncedWrite(path, 'a', entry.line);
    return { appended: entry.identity };
  } finally {
    releaseLock(lock, lockPath);
  }
}

// { ledger } to { entries, torn } or { refused, at }.
function read(request) {
  const result = ledger.readLedger(readBytes(request.ledger));
  if (result.refused) return { refused: 'corrupt', at: result.at };
  return { entries: result.entries, torn: result.torn };
}

module.exports = { append, read };
