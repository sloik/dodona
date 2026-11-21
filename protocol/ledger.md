# The ledger file

Draft **0.1**. The ledger is where a kernel keeps what it has seen: results of checks, and acts of judgement. This document fixes its form on disk, so that two kernels can read each other's ledgers and so that damage is noticed.

## An entry

An entry is an object with three fields:

| Field | Meaning |
|---|---|
| `previous` | The identity of the entry before it, or null for the first |
| `kind` | A name for what the entry is: any non-empty string. `evidence` and `act` take part in status; a reader keeps entries of every other kind and gives them no meaning |
| `body` | The content. Its shape depends on the kind |

An entry has exactly these three fields. An object with a fourth field, or without one of the three, is not an entry, and neither is anything that is not an object.

The **identity** of an entry is the identity of that object under the [canonical encoding](canonical-encoding.md). Because each entry names the one before it, changing, removing or reordering any entry breaks every identity after it.

## On disk

The ledger is one file. Each entry is one line:

```
dodona1 <length> <checksum> <payload>
```

- `dodona1` is the format marker.
- `<payload>` is the canonical encoding of the entry, in UTF-8. It contains no line feed, because the encoding escapes them.
- `<length>` is the number of bytes in the payload, in decimal, with no sign and no leading zero.
- `<checksum>` is the SHA-256 of the payload, as 64 lowercase hexadecimal digits.
- The four parts are separated by single spaces and the line ends with one line feed. Nothing else is allowed: no carriage return, no blank lines.

So a line is exactly `dodona1`, one space, the length, one space, 64 lowercase hexadecimal digits, one space, the payload, and a line feed. Two spaces, a tab, a byte-order mark, an empty line, bytes after the payload, an uppercase digit in the checksum, or another first word each make the line corrupt.

## Reading

1. A file that does not exist, or is empty, has no entries.
2. If the file does not end with a line feed, the bytes after the last line feed are a **torn** final entry: a write that did not finish. They are ignored, and the reader says the ledger was torn. Nothing else about the file is excused by this.
3. Every complete line must be well formed, have the right length and checksum, hold a payload that is exactly the canonical encoding of an entry, nested no deeper than 64 levels (the entry itself is the first; a list or an object inside it adds one), and name the identity of the line before it as `previous`. The length and the checksum are both compared with the payload; neither stands in for the other. `previous` must be exactly the identity of the entry before, not of an earlier one, and null in the first entry only. An entry of a kind the reader gives no meaning is read like any other. The first line that fails makes the whole ledger **corrupt**: the reader refuses it and says which line, counting from 1. A corrupt ledger is never read in part. The depth limit is there so that every reader can read every entry. What carries entries further, such as a status report or the scenario a status command judged, nests deeper, and is read without that limit.

A torn ending is the mark of a crash and is safe to drop. Anything else wrong is the mark of something having altered the file, and is not.

## Appending

1. Take the lock: create the file `<ledger>.lock` in a way that fails if it already exists. If it exists, wait and try again, up to the time the caller allows, then refuse with `locked`. On some systems, creating the lock file while another kernel is removing it fails with a permission error instead of "already exists"; a kernel treats both as the lock being held and tries again until its wait runs out. Found on Windows, where one of two kernels writing at once gave up.
2. Read the ledger. If it is corrupt, release the lock and refuse with `corrupt`.
3. If it was torn, cut the torn bytes off first.
4. Build the entry with `previous` set to the identity of the last entry, write its line, and make sure it has reached the disk.
5. Release the lock by removing the lock file.

The caller supplies `kind` and `body`. A request with no `kind` that is a string, with no `body`, or whose entry would nest deeper than 64 levels (so that no reader could read it), is refused with `bad-request` and nothing is written: no entry, no file and no lock left behind. The request is judged before the ledger is read, so `bad-request` comes before `corrupt`, and a request nested too deep to be read at all is `bad-request` too. The kernel supplies `previous`; a caller cannot choose it. A kernel reports a result to anyone only after the entry behind it has been written.

A lock file left behind by a kernel that crashed stays until someone removes it. That is deliberate: a kernel cannot tell a crashed writer from a slow one.

## What the file does not protect

The chain and the checksums show that a ledger has not been damaged or edited in the middle. They do not show who wrote it. Anyone who can write the file can append a well-formed entry. Whether an entry counts depends on its content: an evidence record counts only if its key matches the inputs it states and its writer is one the reader accepts; an act counts above the lowest levels only if a harness the policy names has vouched for it. Those rules are in [the data model](../MODEL.md) and the conformance kit.

## Test cases

`conformance/ledger/cases.json` describes ledgers and what a reader must make of them, including a torn ending at every possible byte and each kind of corruption. `conformance/ledger/more-damage.json` gives more damaged ledgers, each as a whole file, and requests to append that must be refused. `tools/run_ledger_cases.py` builds the files itself, byte for byte, from the reference encoding, so a kernel's output is compared with something no kernel produced.
