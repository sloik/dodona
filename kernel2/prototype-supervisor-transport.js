'use strict';
// PROTOTYPE, unwired, Unix only. Nothing published requires this file; only its tests do.
//
// The parent's side of the private channel to prototype-unix-supervisor.js, shaped as the
// `launch` that prototype-supervised-executor.js's superviseBatch is given. The parent
// holds no process id and sends no signal: it asks over the channel, watches how the
// supervisor ends, and, when it gives up, closes the channel, which the supervisor reads
// as a request to end its own group.
//
// What it reports, and no more:
// - ownership 'confirmed' only on the supervisor's `owned`, sent after it checked that it
//   leads a group with its own id and after the executor, started undetached inside that
//   group, was spawned;
// - input written only on `input-written`, which the supervisor sends once the
//   executor's standard input has taken the whole batch and been closed;
// - the output's end only on `stdout-end`, the real end of the pipe the supervisor holds
//   only for reading;
// - cleanup 'acknowledged' only when the supervisor said `cleanup-issuing` after being
//   asked and then ended by SIGKILL, the signal it sends its own group. That is never
//   taken as proof that every process ended;
// - `lost` when the supervisor ends, fails or leaves the channel before that, or breaks
//   the protocol.

const path = require('node:path');
const { PassThrough, Writable } = require('node:stream');

const SUPPORTED = ['linux', 'darwin'];

function realSpawnSupervisor() {
  const { spawn } = require('node:child_process');
  return spawn(process.execPath, [path.join(__dirname, 'prototype-unix-supervisor.js')], {
    detached: true, stdio: ['ignore', 'ignore', 'ignore', 'ipc'], serialization: 'advanced', windowsHide: true,
  });
}

// `spawnSupervisor()` -> a ChildProcess-like with send, on, once, connected, disconnect,
// unref. Throws, before anything is started, on a platform this prototype does not serve.
function makeLaunch({ platform, spawnSupervisor = realSpawnSupervisor }) {
  return (argv, cwd) => {
    if (!SUPPORTED.includes(platform)) throw new Error('unavailable: no reviewed process ownership on this platform');
    return connect(spawnSupervisor(), argv, cwd);
  };
}

function connect(child, argv, cwd) {
  let phase = 'starting'; // starting -> owned | not-started | refused
  let outputDone = false;
  let exitSeen = false;
  let cleanupAsked = false;
  let cleanupIssuing = false;
  let gone = false;
  let inputCallback = null;
  let settleOwnership;
  let settleExited;
  let settleLost;
  let settleCleanup = null;

  const sup = {};
  sup.ownership = new Promise((resolve) => { settleOwnership = resolve; });
  sup.exited = new Promise((resolve) => { settleExited = resolve; });
  sup.lost = new Promise((resolve) => { settleLost = resolve; });
  sup.stdout = new PassThrough();
  // A broken output can arrive in the same turn as ownership, before exchange listens.
  sup.stdout.on('error', () => {});

  const lose = () => {
    if (gone) return;
    gone = true;
    settleLost();
    if (inputCallback) {
      const callback = inputCallback;
      inputCallback = null;
      callback(new Error('supervisor lost'));
    }
    if (settleCleanup) settleCleanup('lost');
  };

  const chunks = [];
  sup.stdin = new Writable({
    write(chunk, encoding, callback) {
      chunks.push(Buffer.from(chunk));
      callback();
    },
    final(callback) {
      if (phase !== 'owned' || gone || !child.connected) {
        callback(new Error('input before ownership, or no channel'));
        return;
      }
      inputCallback = callback;
      child.send({ type: 'input', data: Buffer.concat(chunks) });
    },
  });
  sup.stdin.on('error', () => {});

  sup.requestCleanup = () => new Promise((resolve) => {
    cleanupAsked = true;
    if (gone) {
      resolve('lost');
      return;
    }
    settleCleanup = resolve;
    if (child.connected) child.send({ type: 'cleanup' });
    else lose();
  });

  sup.release = () => {
    if (child.connected) child.disconnect();
    child.unref();
  };

  const onMessage = (message) => {
    if (gone) return;
    const type = message !== null && typeof message === 'object' ? message.type : undefined;
    if (phase === 'starting') {
      if (type === 'owned') phase = 'owned';
      else if (type === 'not-started' || type === 'refused') phase = type;
      else if (type !== 'cleanup-issuing' && type !== 'cleanup-impossible') return lose();
      if (phase !== 'starting') return settleOwnership(phase === 'owned' ? 'confirmed' : phase);
    }
    if (type === 'cleanup-issuing') {
      // Unasked, the supervisor is ending its group on its own: the batch is lost.
      if (!cleanupAsked) return lose();
      cleanupIssuing = true;
      return undefined;
    }
    if (type === 'cleanup-impossible') return lose();
    if (phase !== 'owned') return lose();
    if (type === 'stdout' && !outputDone && message.data instanceof Uint8Array) {
      // Structured cloning may give a plain Uint8Array for a Buffer; the bytes are the same.
      sup.stdout.write(Buffer.from(message.data.buffer, message.data.byteOffset, message.data.byteLength));
      return undefined;
    }
    if ((type === 'stdout-end' || type === 'stdout-broken') && !outputDone) {
      outputDone = true;
      if (type === 'stdout-end') sup.stdout.end();
      else sup.stdout.destroy(new Error('the executor\'s output failed'));
      return undefined;
    }
    if (type === 'executor-exit' && !exitSeen) {
      exitSeen = true;
      settleExited(Number.isSafeInteger(message.code) ? message.code : null);
      return undefined;
    }
    if ((type === 'input-written' || type === 'input-failed') && inputCallback) {
      const callback = inputCallback;
      inputCallback = null;
      callback(type === 'input-written' ? null : new Error('the batch could not be written'));
      return undefined;
    }
    return lose();
  };

  // Node does not order 'exit' against messages still unread on the channel; 'disconnect'
  // comes once the channel is drained. So the end is judged only when both have come.
  let exitedWith = null;
  let disconnected = false;
  const judgeEnd = () => {
    if (exitedWith === null || !disconnected || gone) return;
    if (cleanupIssuing && exitedWith.signal === 'SIGKILL') {
      if (settleCleanup) settleCleanup('acknowledged');
      return;
    }
    lose();
  };
  child.on('message', onMessage);
  child.once('error', lose);
  child.once('disconnect', () => {
    disconnected = true;
    // Drained and no `cleanup-issuing` among what came: the supervisor is lost.
    if (!cleanupIssuing) lose();
    else judgeEnd();
  });
  child.once('exit', (code, signal) => {
    exitedWith = { signal };
    judgeEnd();
  });
  if (child.connected) child.send({ type: 'start', argv, cwd });
  else lose();
  return sup;
}

module.exports = { makeLaunch, connect, SUPPORTED };
