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
  // No entry nested deeper than a reader reads (protocol/ledger.md): it is never written.
  if (ledger.tooDeep({ previous: null, kind: request.kind, body: request.body })) return { refused: 'bad-request' };
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

// Writes `bytes` at `at` and on, as many writes as it takes: a write that makes no
// progress fails. Throws on any failure.
function writeWhole(io, descriptor, bytes, at) {
  let done = 0;
  while (done < bytes.length) {
    const wrote = io.writeSync(descriptor, bytes, done, bytes.length - done, at + done);
    if (!Number.isSafeInteger(wrote) || wrote <= 0) throw new Error(`a write made no progress (${wrote})`);
    done += wrote;
  }
}

// Several entries, [{kind, body}], appended in order under one lock, as one write: the
// folders on the way made, the lock taken (waited for up to `waitMs`), `check()` asked
// again under the lock (a reason it gives refuses, before the ledger is read), an ending
// cut short cut off, each entry chained to the one before it, every byte written at its
// place and the file flushed to disk, the lock released. If cutting, writing or flushing
// fails, the file is cut back to the whole entries it held and flushed again under the
// same lock, so a refused append leaves none of its entries; `rolled_back` says whether
// that was done. { appended: [identities] }, or { refused: 'locked', 'corrupt', 'unsafe'
// or 'not-written', detail, rolled_back }. An entry that cannot be encoded throws before
// anything is written. `io` is node:fs unless a test gives another.
//
// Where the cleanup ends: the lock is released last. If that fails, the answer is
// { refused: 'not-unlocked', detail, held }, where `held` is what was done under the lock
// (an append whose entries are written and flushed, or a refusal with its rolled_back),
// as far as it was seen; nothing further is undone, and the lock file may remain.
function appendAll(path, entries, waitMs, { check = () => null, io = fs, release = releaseLock } = {}) {
  fs.mkdirSync(require('node:path').dirname(path), { recursive: true });
  const lockPath = `${path}.lock`;
  const held = takeLock(lockPath, waitMs);
  if (held === null) return { refused: 'locked' };
  let done;
  try {
    done = appendHeld(path, entries, check, io);
  } catch (failure) {
    try {
      release(held, lockPath);
    } catch (unlock) {
      failure.message = `${failure.message}; and the lock not released: ${unlock.message}`;
    }
    throw failure;
  }
  try {
    release(held, lockPath);
  } catch (unlock) {
    return { refused: 'not-unlocked', detail: unlock.message, held: done };
  }
  return done;
}

function appendHeld(path, entries, check, io) {
  {
    const unsafe = check();
    if (unsafe !== null) return { refused: 'unsafe', detail: unsafe };
    const before = ledger.readLedger(readBytes(path));
    if (before.refused !== undefined) return { refused: 'corrupt' };
    const lines = [];
    const identities = [];
    let previous = before.last;
    for (const { kind, body } of entries) {
      const entry = ledger.encodeEntry({ previous, kind, body });
      lines.push(entry.line);
      identities.push(entry.identity);
      previous = entry.identity;
    }
    const whole = before.keep;
    const descriptor = io.openSync(path, fs.constants.O_RDWR | fs.constants.O_CREAT);
    try {
      try {
        if (before.torn === true) io.ftruncateSync(descriptor, whole);
        writeWhole(io, descriptor, Buffer.concat(lines), whole);
        io.fsyncSync(descriptor);
        return { appended: identities };
      } catch (failure) {
        try {
          io.ftruncateSync(descriptor, whole);
          io.fsyncSync(descriptor);
        } catch (undo) {
          return { refused: 'not-written', detail: `${failure.message}; and not cut back: ${undo.message}`, rolled_back: false };
        }
        return { refused: 'not-written', detail: failure.message, rolled_back: true };
      }
    } finally {
      io.closeSync(descriptor);
    }
  }
}

// { ledger } to { entries, torn } or { refused, at }.
function read(request) {
  const result = ledger.readLedger(readBytes(request.ledger));
  if (result.refused) return { refused: 'corrupt', at: result.at };
  return { entries: result.entries, torn: result.torn };
}

module.exports = { append, appendAll, read };
