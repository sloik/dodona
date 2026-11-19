'use strict';
// Starting a command the kernel is given, and ending it with every process it started
// (conformance/README.md, "Session": the provider's process group on Unix, its job on
// Windows).
//
// The kernel names no program of its own here: what it starts is the argument list it
// was given.
//
// On Linux and macOS the command is started in a process group of its own, and ending
// it signals the whole group at once; that reaches processes whose parent has already
// exited. A process that leaves the group by starting a session of its own is beyond
// what the contract promises.
//
// On Windows Node can make no job object. A process keeps the id of its parent after
// the parent has exited, so the kernel reads the process table, through the operating
// system's own management interface, and ends everything below the command. If the
// table cannot be read the kernel does not quietly end less: it fails, loudly.

const { spawn, spawnSync } = require('node:child_process');

const POSIX = process.platform !== 'win32';

// Starts argv with its standard streams as pipes.
function start(argv, cwd) {
  const child = spawn(argv[0], argv.slice(1), {
    cwd,
    stdio: ['pipe', 'pipe', 'pipe'],
    detached: POSIX,
    windowsHide: true,
  });
  child.hasExited = false;
  child.exited = new Promise((resolve) => {
    child.once('exit', () => resolve());
    child.once('error', () => resolve());
  }).then(() => {
    child.hasExited = true;
  });
  child.stdin.on('error', () => {});
  child.stdout.on('error', () => {});
  child.stderr.on('error', () => {});
  return child;
}

// The Windows process table as [pid, parent pid] pairs. Throws if it cannot be read.
function windowsTable() {
  const run = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId) $($_.ParentProcessId)" }'],
  { encoding: 'utf8', windowsHide: true });
  const pairs = [];
  for (const line of (typeof run.stdout === 'string' ? run.stdout : '').split(/\r?\n/)) {
    const fields = line.trim().split(/\s+/);
    if (fields.length === 2 && /^\d+$/.test(fields[0]) && /^\d+$/.test(fields[1])) pairs.push([Number(fields[0]), Number(fields[1])]);
  }
  if (run.status !== 0 || pairs.length === 0) {
    throw new Error('cannot read the process table, so the processes a command started cannot all be ended');
  }
  return pairs;
}

// The processes in the table below any of `known` that are not themselves known.
function below(pairs, known) {
  const found = [];
  const seen = new Set(known);
  let grew = true;
  while (grew) {
    grew = false;
    for (const [pid, parent] of pairs) {
      if (!seen.has(pid) && seen.has(parent)) {
        seen.add(pid);
        found.push(pid);
        grew = true;
      }
    }
  }
  return found;
}

function kill(pid) {
  try {
    process.kill(pid, 'SIGKILL');
  } catch (error) {
    // already gone
  }
}

function killGroup(pid) {
  try {
    process.kill(-pid, 'SIGKILL');
  } catch (error) {
    // the group is already empty
  }
}

function pause(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Ends the child and every process it started, and waits (bounded) until the child itself is gone.
async function endTree(child) {
  const pid = child.pid;
  if (pid === undefined) return;
  if (POSIX) {
    killGroup(pid);
    kill(pid);
  } else {
    kill(pid);
    const known = new Set([pid]);
    for (let round = 0; round < 4; round += 1) {
      const found = below(windowsTable(), known);
      for (const other of found) {
        known.add(other);
        kill(other);
      }
      if (found.length === 0) break;
    }
  }
  await Promise.race([child.exited, pause(2000)]);
}

module.exports = { start, endTree, pause, below };
