'use strict';
// Starting a command the kernel is given, and ending it with every process it started
// (conformance/README.md, "Session": the provider's process group on Unix, its job on
// Windows; "Host checks": the executor's the same).
//
// The kernel names no program of its own here: what it starts is the argument list it
// was given.
//
// On Linux and macOS the command is started in a process group of its own, and ending
// it signals the whole group at once; that reaches processes whose parent has already
// exited. A process that leaves the group by starting a session of its own is beyond
// what the contract promises.
//
// On Windows Node can make no job object. The kernel reads the process table through
// the operating system's management interface before it ends anything, ends the tree
// below the command while the command still holds its id (`taskkill /T`), and then
// ends what the table showed below it, which reaches processes whose parent has
// already exited, since a process keeps its parent's id. A parent's id can be reused
// once the parent is gone, so a process counts as below another only if it was created
// after it, and below a command that has exited only if it was created before any
// process that took the command's id. If the table cannot be read in time, the kernel
// does not quietly end less: it fails, loudly.

const { spawn, spawnSync } = require('node:child_process');

const POSIX = process.platform !== 'win32';
const TABLE_TIMEOUT_MS = 30000;
// FILETIME: 100-nanosecond intervals since 1601-01-01 UTC.
const FILETIME_AT_EPOCH = 116444736000000000n;
// How far a process's recorded creation may fall before the moment it was started from
// here, for clocks read in different ways.
const CREATION_SLACK = 20000000n; // two seconds

function fileTimeNow() {
  return FILETIME_AT_EPOCH + BigInt(Date.now()) * 10000n;
}

// Starts argv with its standard streams as pipes.
function start(argv, cwd) {
  const startedAt = fileTimeNow() - CREATION_SLACK;
  const child = spawn(argv[0], argv.slice(1), {
    cwd,
    stdio: ['pipe', 'pipe', 'pipe'],
    detached: POSIX,
    windowsHide: true,
  });
  child.startedAt = startedAt;
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

// The Windows process table as [{ pid, parent, created }], created a FILETIME BigInt
// (0n when the system gives none). Throws if it cannot be read in time.
function windowsTable() {
  const run = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    'Get-CimInstance Win32_Process | ForEach-Object { $c = 0; if ($_.CreationDate) { $c = $_.CreationDate.ToFileTimeUtc() }; '
    + '"$($_.ProcessId) $($_.ParentProcessId) $c" }'],
  { encoding: 'utf8', windowsHide: true, timeout: TABLE_TIMEOUT_MS });
  const table = [];
  for (const line of (typeof run.stdout === 'string' ? run.stdout : '').split(/\r?\n/)) {
    const fields = line.trim().split(/\s+/);
    if (fields.length === 3 && fields.every((field) => /^\d+$/.test(field))) {
      table.push({ pid: Number(fields[0]), parent: Number(fields[1]), created: BigInt(fields[2]) });
    }
  }
  if (run.error !== undefined || run.status !== 0 || table.length === 0) {
    throw new Error('cannot read the process table in time, so the processes a command started cannot all be ended');
  }
  return table;
}

// The processes in `table` below the root, as [{ pid, created }]. The root was started
// at `startedAt` and has exited when `exited` is true. A process is below another only if created after it;
// below an exited root only if created before whatever took the root's id since.
function below(table, root, startedAt, exited) {
  const created = new Map([[root, startedAt]]);
  let reusedAt = null;
  if (exited) {
    const taker = table.find((entry) => entry.pid === root);
    if (taker !== undefined) reusedAt = taker.created;
  }
  const found = [];
  let grew = true;
  while (grew) {
    grew = false;
    for (const entry of table) {
      if (created.has(entry.pid) || !created.has(entry.parent)) continue;
      if (entry.created < created.get(entry.parent)) continue;
      if (entry.parent === root && reusedAt !== null && entry.created >= reusedAt) continue;
      created.set(entry.pid, entry.created);
      found.push({ pid: entry.pid, created: entry.created });
      grew = true;
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

function endWindowsTree(child) {
  const pid = child.pid;
  const found = below(windowsTable(), pid, child.startedAt, child.hasExited);
  if (!child.hasExited) {
    spawnSync('taskkill', ['/T', '/F', '/PID', String(pid)], { windowsHide: true, timeout: TABLE_TIMEOUT_MS });
  }
  kill(pid);
  for (const other of found) kill(other.pid);
  // Anything started in the meantime below what was found, if it still holds its id.
  const again = windowsTable();
  for (const other of found) {
    const entry = again.find((item) => item.pid === other.pid);
    if (entry === undefined || entry.created !== other.created) continue;
    for (const late of below(again, other.pid, other.created, false)) kill(late.pid);
  }
}

// Ends the child and every process it started, and waits (bounded) until the child itself is gone.
async function endTree(child) {
  const pid = child.pid;
  if (pid === undefined) return;
  if (POSIX) {
    killGroup(pid);
    kill(pid);
  } else {
    endWindowsTree(child);
  }
  await Promise.race([child.exited, pause(2000)]);
}

module.exports = { start, endTree, pause, below };
