# kernel2

A second dodona kernel, written in JavaScript for Node.js (20 or later) using only Node's built-in modules. There are no packages, no build step and no lock file.

It is an independent implementation: it was written from the project's documents and its conformance kit alone, without reading the first kernel (`kernel/`, in Rust), the reference path check or the model files under `spec/`. If it and the first kernel ever disagree on an input that both pass the kit, the kit is missing a scenario.

It does what the kit can judge: obligation and intent status, the planner, assurance, trees, attempts, platforms, decisions, the canonical encoding and the path check, and, as a host, a provider session and one check taken through a provider and an executor to a verdict ([decision 0033](../decisions/0033-a-kernel-hosts-providers.md)), and the status of a whole project from its project file, its providers and its ledgers ([decision 0034](../decisions/0034-a-kernel-runs-a-project-and-reports-its-status.md)). It is not a usable dodona.

## Running it

Each command reads standard input and prints one JSON object, except `session`, which reads nothing.

    node kernel2/dodona-kernel2.js scenario     one conformance scenario
    node kernel2/dodona-kernel2.js canonical    a JSON text, to its canonical form and hash
    node kernel2/dodona-kernel2.js path         {"hex": "..."} to accepted or refused
    node kernel2/dodona-kernel2.js path-set     {"paths": [...]} to the colliding pairs
    node kernel2/dodona-kernel2.js states       single states, as tools/check_states.py sends them
    node kernel2/dodona-kernel2.js check        one check, from a provider to a verdict (conformance/README.md, "Host checks")
    node kernel2/dodona-kernel2.js run          run a project's checks and record completed verdicts;
    node kernel2/dodona-kernel2.js status       a project's status (conformance/README.md, "How a project's status is judged");
                                                it answers every input with one object and exits 0, a refusal included
    node kernel2/dodona-kernel2.js session --deadline-ms N --max-line N --max-log N -- <provider command>
                                                one provider session (conformance/README.md, "Session")

The provider and the executor are commands the kernel is given; it names no tool. To end every process a provider or an executor started, the kernel starts each in a process group of its own on Linux and macOS and ends the group. On Windows, where Node can make no job object, it reads the process table (`Get-CimInstance Win32_Process`) before ending anything, ends the tree with `taskkill /T` while the command still holds its id, and then ends what the table showed below it, since a process keeps its parent's id after the parent has exited. A process counts as below another only if it was created after it, so a reused id cannot bring in an unrelated process. If the table cannot be read within 30 seconds, the command fails rather than end less.

## Judging it

From the repository root:

    python3 tools/run_kit.py -- node kernel2/dodona-kernel2.js scenario
    python3 tools/run_vectors.py -- node kernel2/dodona-kernel2.js canonical
    python3 tools/run_path_vectors.py -- node kernel2/dodona-kernel2.js path path-set
    python3 tools/run_harness_check.py -- node kernel2/dodona-kernel2.js scenario
    node --test kernel2/test.js
    node kernel2/test-normalization.js .ucd
    python3 tools/run_attest_check.py -- node kernel2/dodona-kernel2.js scenario
    python3 tools/run_provider_cases.py -- node kernel2/dodona-kernel2.js session
    python3 tools/run_check_cases.py -- node kernel2/dodona-kernel2.js check
    python3 tools/run_status_cases.py --jobs 3 --kernel <the first kernel> -- node kernel2/dodona-kernel2.js status
    node kernel2/plant.js
    node --test kernel2/test-plant.js

`plant.js` copies the kernel, plants defects from `defects.json` one at a time, and judges each copy. Changes to a host or project status module go to the judge for that module first. A rejection counts when the judge reports a complete tally and the same named case rejects on replay. The scenario judge counts `scenarios`, the ledger judge counts `checks`, and the core-key, canonical and path judges count `vectors`. Host-check and status count `judged` with skips tallied separately. The remaining judges count `cases`. If only the unit tests reject a copy, the kit reports a miss. A copy that cannot load is broken. The runner restores each mutation and removes its own temporary copy. Hosted CI exercises this behavior with mocked subprocesses in `test-plant.js`.

The status judge uses the first kernel's `scenario` command to recompute the report. Build the first kernel in release mode from the repository's `kernel/` directory, or name its executable with `DODONA_OTHER_KERNEL`. `DODONA_STATUS_JOBS` controls case concurrency and defaults to three. `node kernel2/plant.js FILE...` tries the defects in the named files. The runner starts its judges through `DODONA_PYTHON` when set, or through `python3` on Unix and `python` on Windows.

The repository checker detects missing source anchors from `defects.json`. For example, the cross-platform assurance defect changes the evidence supplied to the level calculation while keeping the literal obligation name as an own property.

A defect with a `witness` must produce a repeated rejection from that exact judge and case. The validation witnesses cover a held ledger lock, a provider deadline and project status input. A different named rejection leaves the defect uncaught.

## Unicode

The path rules are pinned to Unicode 15.1. The kernel does not use Node's `normalize`, case conversion or Unicode property classes, because those follow whatever Unicode the platform carries. `unicode-tables.js` is generated by `gen-unicode-tables.js` from the official data files; its header names the version and the SHA-256 of each source file.

    node kernel2/gen-unicode-tables.js <directory with the Unicode 15.1.0 data files>

The data files are not committed. `test-normalization.js` runs every line of `NormalizationTest.txt` through the kernel's NFC and NFD.

## Layout

One module per area (`evidence.js`, `intent.js`, `plan.js`, `assurance.js`, `tree.js`, `attempts.js`, `platforms.js`, `decisions.js`, `canonical.js`, `strict-json.js`, `paths.js`, `unicode.js`). The host is `session.js` and `check.js`, with `wire.js` (reading messages), `processes.js` (starting and ending commands) and `host-rules.js` (the rules of a check, pure functions). The rules are pure functions. `project-status.js` is the `status` command: it reads the project and its ledgers, hosts a session with each provider through the host modules, and computes its report with the same status rules as `scenario`. Only `dodona-kernel2.js`, `ledger-file.js`, `project-status.js` and the host modules read or write. The `scenario` and `states` commands call the same rule functions. Input is read into own data properties (`plain.js`), and the `status` command and the status report's obligations are built the same way, so that an obligation named `__proto__` is kept as a key. The status rules still build their maps keyed by intent and by criterion by assigning to a computed key, which an intent or criterion named `__proto__` does not survive; no case judges that yet.

The JavaScript planted-defect runner accepts `--shard INDEX COUNT`, with zero-based positions in the full manifest. Each shard runs the unchanged baseline and repeats every credited named rejection. Its summary marks the selected inventory only. The repository workflow requires all JavaScript shards to succeed.

The `run` command uses the status command's project snapshot, keeps only checking provider sessions open and records completed verdicts in the selected ledger. The project-run judge compares its report with the subsequent `status` report and verifies that current results are reused. Focused tests for the scheduling and ledger paths run with `node --test kernel2/test-run.js`.
