# Seed kernel

A small first kernel, written from [the conformance kit](../conformance/README.md) and [the ledger format](../protocol/ledger.md). It is not a usable dodona: it runs no providers, plans no work and has no agent interface. Passing the kit is sampled evidence, not a proof.

It uses the standard library only and has no unsafe code.

## Commands

The kernel reads one JSON value on standard input, takes the command as its one argument, and prints one JSON object.

| Command | Does |
|---|---|
| `scenario` | Judges a sequence of steps of any kind in the kit: evidence, intent, plan, assurance, tree, attempts, platforms, decisions, acts, status |
| `states` | Judges independent evidence or intent states given in one input |
| `canonical` | Gives the canonical encoding of a value and its hash, or refuses it |
| `key` | Gives the core key of an evidence record from its preimage, or refuses it |
| `path`, `path-set` | Checks one path given as hexadecimal bytes; lists the paths in a set that collide |
| `ledger-read` | Reads a ledger file: its entries and whether its ending was torn, or `corrupt` and the line |
| `ledger-append` | Adds one entry to a ledger file, or refuses with `locked` or `corrupt` |

A refusal the contract names is an answer, with exit status 0. Anything else the kernel cannot handle (an unknown command or kind, input of the wrong shape, a file it cannot read or write) prints nothing on standard output and ends with a status that is not 0.

A step that has nothing to act on changes nothing: finishing a run that is not in flight, closing a ticket that is not open, a check or edit of a tree node, obligation or gate that is not there.

## One copy of each rule

- Grading an act is `acts::grade`. Acts scenarios report it; status scenarios count with it.
- The status of an obligation from the verdicts that count is `evidence::status`, for evidence scenarios, `states` and status scenarios.
- The status of an intent, and whether a criterion is met, are in `intent.rs`, for intent scenarios, `states` and status scenarios. A criterion that nothing checks is never met.
- Identity, core keys and hexadecimal are in `canonical.rs`. In status scenarios an evidence record whose preimage cannot be keyed is rejected.

## The ledger

`ledger-append` takes the lock file, reads the ledger, cuts off a torn ending, writes the new line, syncs the file, and only then removes the lock. The lock is removed on every way out, including errors. A lock left by a kernel that crashed stays, as the format says. Syncing the directory after the file is first created is not done: the standard library has no portable way.

## Build and judge

From the repository root (on Windows the executable ends in `.exe`):

```text
cargo build --release --manifest-path kernel/Cargo.toml
cargo test --manifest-path kernel/Cargo.toml
python3 tools/run_kit.py -- kernel/target/release/dodona-kernel scenario
python3 tools/run_vectors.py -- kernel/target/release/dodona-kernel canonical
python3 tools/run_path_vectors.py -- kernel/target/release/dodona-kernel path path-set
python3 tools/run_key_vectors.py -- kernel/target/release/dodona-kernel key
python3 tools/run_ledger_cases.py -- kernel/target/release/dodona-kernel
python3 tools/kit_adequacy.py
```

`defects.json` lists defects to plant in this kernel, one text replacement each. `tools/kit_adequacy.py` plants them one at a time in a copy and reports whether the kit rejects each.

## Unicode tables

The checked-in tables use Unicode 15.1.0. To regenerate them, put the five official data files named in the table header in a directory and run:

```text
python3 tools/gen_unicode_tables.py <data-directory>
```

The header records the SHA-256 digest of every input. One test is ignored by default because it needs a file that is not in the repository: the full Unicode normalization test reads `NormalizationTest.txt` from the directory named by `DODONA_UCD_DIR`:

```text
cargo test --manifest-path kernel/Cargo.toml normalization_conformance -- --ignored
```
