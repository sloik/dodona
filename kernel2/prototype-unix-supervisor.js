'use strict';
// PROTOTYPE, unwired, Unix only. Nothing published requires this file; only
// prototype-supervisor-transport.js names it, and only its tests reach that.
//
// The supervisor: a same-runtime process the parent starts detached, so that it leads a
// new session and process group of its own. It starts the executor as an ordinary,
// undetached child, which therefore joins that group, and relays over the private IPC
// channel what the parent needs to judge step 12 (conformance/README.md): ownership, input
// completion, the executor's exit, its standard output up to and including the first
// line feed, and that output's real end.
//
// Holding no writer: the supervisor keeps only the read end of the executor's standard
// output and the write end of its standard input, so the end of output it reports is the
// end of every writer in the group, not its own. The IPC descriptor (3) is overwritten in
// the executor by a pipe whose other end the supervisor closes at once, so the executor
// cannot reach the channel.
//
// Cleanup: on the parent's request, or when the channel is lost, and only while it is
// alive and still leads its own group, the supervisor says it is issuing cleanup and then
// sends SIGKILL to its own group, itself included. It never signals any other id. Neither
// its message nor its death shows that every process ended: a process that left the group
// is beyond the contract (conformance/README.md, "Not yet in the kit"), and whether a
// process forked during the signal is reached is up to the operating system.
//
// Protocol (parent -> supervisor): {type:'start', argv, cwd}, {type:'input', data},
// {type:'cleanup'}. (supervisor -> parent): {type:'owned'} | {type:'not-started'} |
// {type:'refused'}; {type:'input-written'} | {type:'input-failed'}; {type:'stdout', data}
// (until and including the first line feed), {type:'stdout-end'} | {type:'stdout-broken'};
// {type:'executor-exit', code, signal}; {type:'cleanup-issuing'} | {type:'cleanup-impossible'}.

// `deps`: channel ({send(message, callback), on(event, fn), connected}), spawnExecutor
// (argv, cwd) -> child, leadsOwnGroup() -> boolean, killOwnGroup(), exit(code).
function runSupervisor(deps) {
  const { channel } = deps;
  let started = false;
  let issued = false;
  let child = null;

  const send = (message, callback) => {
    if (!channel.connected) {
      if (callback) callback(new Error('channel lost'));
      return;
    }
    channel.send(message, callback);
  };

  const issue = () => {
    if (issued) return;
    issued = true;
    if (!deps.leadsOwnGroup()) {
      // Not the leader of a group with its own id: there is no group of its own to end,
      // and no other id is ever signalled.
      send({ type: 'cleanup-impossible' }, () => deps.exit(1));
      return;
    }
    // Say so first, then end the group, itself included; the signal is sent whether or
    // not the message could be delivered (send calls back with an error when the channel
    // is gone).
    send({ type: 'cleanup-issuing' }, () => deps.killOwnGroup());
  };

  const start = (argv, cwd) => {
    if (started) return issue();
    started = true;
    if (!Array.isArray(argv) || argv.length === 0 || !argv.every((part) => typeof part === 'string') || typeof cwd !== 'string') {
      send({ type: 'refused' });
      return undefined;
    }
    if (!deps.leadsOwnGroup()) {
      send({ type: 'refused' });
      return undefined;
    }
    child = deps.spawnExecutor(argv, cwd);
    child.once('error', () => {
      if (!child.spawned) send({ type: 'not-started' });
    });
    child.once('spawn', () => {
      child.spawned = true;
      // Descriptor 3 in the executor is this pipe, not the channel; nothing is kept of it.
      if (child.stdio[3]) child.stdio[3].destroy();
      send({ type: 'owned' });
    });
    child.stdin.on('error', () => {});
    let lineDone = false;
    let ended = false;
    child.stdout.on('data', (data) => {
      if (lineDone) return;
      const at = data.indexOf(0x0a);
      send({ type: 'stdout', data: at < 0 ? data : data.subarray(0, at + 1) });
      if (at >= 0) lineDone = true;
    });
    child.stdout.once('end', () => {
      ended = true;
      send({ type: 'stdout-end' });
    });
    child.stdout.once('error', () => {
      if (!ended) send({ type: 'stdout-broken' });
      ended = true;
    });
    child.stdout.once('close', () => {
      if (!ended) send({ type: 'stdout-broken' });
      ended = true;
    });
    child.once('exit', (code, signal) => send({ type: 'executor-exit', code, signal }));
    return undefined;
  };

  channel.on('message', (message) => {
    if (message === null || typeof message !== 'object') return issue();
    if (message.type === 'start') return start(message.argv, message.cwd);
    if (message.type === 'input' && child !== null && child.spawned && message.data instanceof Uint8Array) {
      // Structured cloning may give a plain Uint8Array for a Buffer; the bytes are the same.
      const data = Buffer.from(message.data.buffer, message.data.byteOffset, message.data.byteLength);
      return child.stdin.end(data, (error) => send({ type: error ? 'input-failed' : 'input-written' }));
    }
    // A cleanup request, or anything out of protocol, ends the group.
    return issue();
  });
  // The parent gone, or the channel broken: end the group rather than outlive it.
  channel.on('disconnect', issue);
}

// What the supervisor uses when it really runs. The only signals in this prototype are
// these two calls, and both name the supervisor's own group, by its own id, while it is
// alive and so while that id cannot belong to anything else.
function realDeps() {
  const { spawn } = require('node:child_process');
  const env = { ...process.env };
  delete env.NODE_CHANNEL_FD;
  delete env.NODE_CHANNEL_SERIALIZATION_MODE;
  return {
    channel: process,
    spawnExecutor: (argv, cwd) => spawn(argv[0], argv.slice(1), {
      cwd, env, detached: false, windowsHide: true, stdio: ['pipe', 'pipe', 'ignore', 'pipe'],
    }),
    leadsOwnGroup: () => {
      try {
        process.kill(-process.pid, 0);
        return true;
      } catch (error) {
        return false;
      }
    },
    killOwnGroup: () => process.kill(-process.pid, 'SIGKILL'),
    exit: (code) => process.exit(code),
  };
}

if (require.main === module) {
  if (process.platform === 'win32' || typeof process.send !== 'function') process.exit(2);
  runSupervisor(realDeps());
}

module.exports = { runSupervisor };
