'use strict';
// Starting a command the kernel is given, and ending it with every process it started.
//
// The kernel names no program of its own here: what it starts is the argument list it
// was given. To find what that started it asks the operating system for its process
// table, which is part of the platform, not a tool.
//
// On Linux and macOS the command is started in a process group of its own; ending it
// signals the whole group, which reaches processes whose parent has already exited,
// and also every process found below it in the table, which reaches those that left
// the group. On Windows there are no groups to signal; a process keeps the id of its
// parent after the parent has exited, so the table is walked from the command down.

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
  child.exited = new Promise((resolve) => {
    child.once('exit', () => resolve());
    child.once('error', () => resolve());
  });
  child.hasExited = false;
  child.exited.then(() => {
    child.hasExited = true;
  });
  child.stdin.on('error', () => {});
  child.stdout.on('error', () => {});
  child.stderr.on('error', () => {});
  return child;
}

// The process table as [pid, parent pid] pairs, or [] if it cannot be read.
function table() {
  const run = POSIX
    ? spawnSync('ps', ['-A', '-o', 'pid=', '-o', 'ppid='], { encoding: 'utf8', windowsHide: true })
    : spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId) $($_.ParentProcessId)" }'],
    { encoding: 'utf8', windowsHide: true });
  if (run.status !== 0 || typeof run.stdout !== 'string') return [];
  const pairs = [];
  for (const line of run.stdout.split(/\r?\n/)) {
    const fields = line.trim().split(/\s+/);
    if (fields.length === 2 && /^\d+$/.test(fields[0]) && /^\d+$/.test(fields[1])) pairs.push([Number(fields[0]), Number(fields[1])]);
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
  if (!POSIX) return;
  try {
    process.kill(-pid, 'SIGKILL');
  } catch (error) {
    // the group is already empty
  }
}

function pause(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Ends the child and every process below it, and waits (bounded) until the child itself is gone.
async function endTree(child) {
  const pid = child.pid;
  if (pid === undefined) return;
  const known = new Set([pid]);
  for (let round = 0; round < 4; round += 1) {
    const found = below(table(), known);
    if (round === 0) {
      killGroup(pid);
      kill(pid);
    }
    for (const other of found) {
      known.add(other);
      killGroup(other);
      kill(other);
    }
    if (found.length === 0) break;
  }
  if (POSIX) killGroup(pid);
  await Promise.race([child.exited, pause(2000)]);
}

module.exports = { start, endTree, pause };
