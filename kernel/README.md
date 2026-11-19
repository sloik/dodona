# Seed kernel

A small first kernel, written from [the conformance kit](../conformance/README.md) and [the ledger format](../protocol/ledger.md). It is not a usable dodona: it hosts one provider session or one check at a time ([decision 0033](../decisions/0033-a-kernel-hosts-providers.md)), but plans no work and has no agent interface. Passing the kit is sampled evidence, not a proof.

It uses the standard library only. The one module with unsafe code is `proc.rs`: the calls to the operating system that end a whole process tree (a process group on Unix, a job object on Windows), which the standard library does not offer.

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
| `ledger-append` | Adds one entry to a ledger file, or refuses with `locked`, `corrupt` or `bad-request` |
| `session --deadline-ms N --max-line N --max-log N -- <provider>` | Holds one session with the provider command and reports `ok` or the reason it failed. Reads no input |
| `check` | Takes one obligation through the provider command to a verdict, giving each run to the executor command, or refuses the check with the reason |

A refusal the contract names is an answer, with exit status 0. Anything else the kernel cannot handle (an unknown command or kind, input of the wrong shape, a file it cannot read or write) prints nothing on standard output and ends with a status that is not 0.

The kernel answers every step. A step that has nothing to act on changes nothing: finishing a run that is not in flight, closing a ticket that is not open, naming a criterion, obligation, definition, child, key, platform or intent the scenario does not have, or carrying a gate, verdict, status or level that does not exist. An exception asked for in such a step is reported as not taking effect, at `self`.

## One copy of each rule

- Grading an act is `acts::grade`. Acts scenarios report it; status scenarios count with it.
- The status of an obligation from the verdicts that count is `evidence::status`, for evidence scenarios, `states` and status scenarios.
- The status of an intent, and whether a criterion is met, are in `intent.rs`, for intent scenarios, `states` and status scenarios. A criterion that nothing checks is never met.
- The separation levels are `acts::LEVELS`; the assurance scale is `assurance::SCALE`. The level a status report shows for an intent is on that scale, and an exception in it is graded by `acts::grade` like every other act.
- Identity, core keys and hexadecimal are in `canonical.rs`. A preimage with a field of its own that the definition does not have is refused as `unknown-field`; the contract names no reason for that case. In status scenarios an evidence record whose preimage cannot be keyed is rejected, and an entry that is not a record at all is neither counted nor rejected.
- An act record that is malformed is graded `self`. Nothing above `helper` is granted unless the check value also covers `kind`, `target`, `result` and `lineage`.

## Hosting providers

`session` and `check` follow conformance/README.md, "How a host is judged" and "Host checks". The provider and the executor are commands the kernel is given; it names no tool. Each is started as the root of a process tree (`proc.rs`), and the tree is ended on every way out, including a panic. Standard output is read by a thread in chunks and cut into lines that are never held beyond the limit; standard input is written by a thread of its own, so that sending has a deadline too; standard error is drained all the time and kept up to its cap (`wire.rs`). The kernel waits on a monotonic clock, never on a pipe.

JSON from a provider or an executor is read by `jsonread.rs`, without recursion, so a line nested a million deep is read whole and costs no stack: strictly in a check and for an executor's report (the canonical encoding's refusals, in the order they occur in the text, and the depth measured only once the line is read), as plain JSON in a session (a fraction reads as null, the last of a repeated key stands). Nothing deeper than 64 is kept.

The host's own input, the manifest, the numbered rules for a run and the rules for a final are pure functions in `host.rs` (`read_input`, `manifest`, `run_fault`, `report_fault`, `final_verdict`), each rule on its own line in the contract's order. Where the contract leaves a choice: a check reads lines of at most 1 MiB; a manifest that declares no strength for `obligation.check` has no ceiling, so any `passed` or `failed` is above it; when one rule is broken by several entries, each rule is checked over every entry before the next rule; an argument holding NUL is left to rule 10 by rules 5 and 6 alike; the executor is started in `root`, as the root of a process tree of its own that is ended when it returns, and waited for the check's deadline plus the run's `wall_ms`, at most 24 hours.

## The ledger

`ledger-append` refuses a request with no `kind` that is a non-empty string, or with no `body`, before it touches anything. Otherwise it takes the lock file, reads the ledger, cuts off a torn ending, writes the new line, syncs the file, and only then removes the lock. The lock is removed on every way out, including errors. A lock left by a kernel that crashed stays, as the format says. Syncing the directory after the file is first created is not done: the standard library has no portable way.

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
python3 tools/run_provider_cases.py -- kernel/target/release/dodona-kernel session
python3 tools/run_check_cases.py -- kernel/target/release/dodona-kernel check
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
