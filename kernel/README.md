# Seed kernel

A small first kernel, written from [the conformance kit](../conformance/README.md) and [the ledger format](../protocol/ledger.md). It is not a usable dodona: it hosts one provider session or one check at a time ([decision 0033](../decisions/0033-a-kernel-hosts-providers.md)), and runs one project's checks through a site's executor (decision 0034), but has no agent interface. Passing the kit is sampled evidence, not a proof.

It uses the standard library only. Unsafe operating-system calls in `proc.rs` end a process group on Unix or a job object on Windows. On Windows, `project_status.rs` queries the volume and file number of an open file.

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
| `status` | Reports the status of a whole project from its project file, its providers and its ledgers, or refuses it with the reason. Runs nothing |
| `run` | Does what `status` does, checks every obligation with no current result through its provider and the executor command in batches, records the verdicts in the run's ledger, and reports as `status` does with `counts`; or refuses with the reason |

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

The host's own input, the manifest, the numbered rules for a run and the rules for a final are pure functions in `host.rs` (`read_input`, `manifest`, `run_fault`, `report_fault`, `final_verdict`), each rule on its own line in the contract's order. The executor is started in `root` as the root of a process tree of its own, ended when it returns, and waited for the run's `wall_ms` and a minute more, at most 24 hours; its report is its first line, ended by a line feed alone. After `shutdown` a provider has a second to exit and is then ended, its answer standing. On Windows a process that cannot be put in a job of its own, or let run once it is in it, is ended and the command fails: nothing runs unconfined. Where the contract leaves a choice: a check reads lines of at most 1 MiB; a manifest that declares no strength for `obligation.check` has no ceiling, so any `passed` or `failed` is above it; a check whose input is not JSON at all is refused as `bad-input`, like one that is JSON but not an object.

## A project's status

`status` follows conformance/README.md, "How a project's status is judged", step by step, in `project_status.rs` ([decision 0034](../decisions/0034-a-kernel-runs-a-project-and-reports-its-status.md)). It answers every input with one JSON object and exit status 0, a refusal included. The first rule broken gives the reason and nothing after it is done: every provider's code and every claimed file is read before any provider is started, and a session that said `hello` always ends with `shutdown` and every process of the provider ended.

It holds no status rules of its own. The scenario it judged is run through `status::run`, the code of the `scenario` command, and the report is its last result. Sessions use the check's reading (`wire.rs`, `host::manifest`); ledgers are read by `ledger-read`'s code, so a ledger is exactly as strict here as there. A provider that cannot be confined to a process tree of its own is `provider-not-started`. A claimed file whose name is outside UTF-8 is `unreadable-file`. The kernel compares ledger identity by device and file number on Unix, by volume and file number on Windows, and by resolved path on other systems. On Windows the kernel compares full 128-bit file numbers with both handles open. If either handle cannot supply an identity, it compares resolved paths.

## A project's run

`run` follows conformance/README.md, "How a project's run is judged", in `project_status.rs` ([decision 0034](../decisions/0034-a-kernel-runs-a-project-and-reports-its-status.md)), with standard input, refusals, output and exit status as for `status`. Its own fields (`ledger`, `executor`, `transcript`) are checked first, on their spelling and then on the files, before anything is read or any process started. It reads the project with `status`'s code, keeping the session of each binding that lists `obligation.check` open for the whole run, and plans from `status`'s report: only `unknown` is checked. Each check runs on its binding's own session under the host check rules (`host.rs`), with request ids counted per session; a reason that says a session broke refuses the whole run, and nothing is recorded. The runs open checks ask for go to the executor as one batch, its first line read strictly once it has exited, its output has ended and its input was written whole, all under one deadline. Before recording, every input is read again; the verdicts that stand are appended in one append under the ledger's lock, after the ledger's path is checked again under that lock, and a failed write is cut back. The ledgers are then read again and judged, and the transcript, if asked for, is written as a new file of every message that crossed the wire, `shutdown` included once it was written.

What `run` ends is what it owns: each provider's and each batch's process group (Unix) or job (Windows), as `status` and `check` do. It promises nothing about a process that leaves its group or job, and the threads reading or writing a pipe such a process holds are left after a bounded wait. Opens are not made race-free against someone changing the project's files while it runs.

## The ledger

`ledger-append` refuses a request with no `kind` that is a non-empty string, or with no `body`, or whose entry would nest deeper than 64 levels, before it touches anything. Its request is read by `jsonread.rs`, as strictly as any other command's input, and the depth of the body measured on the text, so a body nested thousands deep is refused like one nested 65 deep, and costs no stack; only a request no deeper than 64 is read as other commands read theirs. A request that is deep only outside its body is judged by its body. Otherwise it takes the lock file, reads the ledger, cuts off a torn ending, writes the new line, syncs the file, and only then removes the lock. The lock is removed on every way out, including errors. A lock left by a kernel that crashed stays, as the format says. Syncing the directory after the file is first created is not done: the standard library has no portable way.

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
python3 tools/run_status_cases.py --kernel node kernel2/dodona-kernel2.js -- kernel/target/release/dodona-kernel status
python3 tools/run_run_cases.py --jobs 2 --kernel node kernel2/dodona-kernel2.js --status "kernel/target/release/dodona-kernel status" -- kernel/target/release/dodona-kernel run
python3 tools/kit_adequacy.py
```

`defects.json` lists defects to plant in this kernel, one text replacement each. `tools/kit_adequacy.py` plants them one at a time in a copy and reports whether the kit rejects each.

A defect with a `witness` names the exact judge and case that must reject the planted kernel on both runs. The repository checker also requires every planted defect to match source text. The validation witnesses cover run description shape, attachment shape and type, and refusal of invalid project status input.

## Unicode tables

The checked-in tables use Unicode 15.1.0. To regenerate them, put the five official data files named in the table header in a directory and run:

```text
python3 tools/gen_unicode_tables.py <data-directory>
```

The header records the SHA-256 digest of every input. One test is ignored by default because it needs a file that is not in the repository: the full Unicode normalization test reads `NormalizationTest.txt` from the directory named by `DODONA_UCD_DIR`:

```text
cargo test --manifest-path kernel/Cargo.toml normalization_conformance -- --ignored
```
