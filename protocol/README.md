# Provider protocol

Draft **0.2**. Not implemented. Below version 1.0 there is no compatibility promise between versions.

A provider is a separate program ([decision 0003](../decisions/0003-providers-are-separate-processes.md)). The kernel starts it and the two exchange JSON messages over standard input and output.

## Framing

- UTF-8, one message per line, delimited by a single line-feed byte. A carriage return before it is a protocol error, as is a byte-order mark.
- A maximum line length, announced by the kernel in `hello`.
- Standard error is drained continuously, capped in size, stored as a log attachment and never interpreted.
- Bulk data, such as tool trees, build outputs and blobs, never travels in a message. It is passed as files in a working directory private to the run.
- The opening exchange includes an echo test with non-ASCII and control characters, so an encoding fault ends the session before any work is done.

## Session

1. The kernel sends `hello` with the protocol versions it speaks and its limits.
2. The provider answers with its [manifest](provider-manifest.schema.json).
3. The kernel sends requests, each with an `id` and a deadline. The provider answers each with a result or an error carrying the same `id`. The kernel drives; the provider never initiates.
4. The kernel sends `shutdown`, or closes the stream and terminates the provider's whole process tree.

A message that fails validation, a missing required field, or a mismatched `id` ends the session; any check in flight in it gets verdict `error`. An answer that arrives after its deadline is logged and dropped. A recorded enumeration result retains each obligation's declared `inputs` as sent. The stage-0 host copies the obligation before separating those paths from its internal representation and supplying the matching file references to a check.

## Capabilities

| Capability | Request carries | Result carries |
|---|---|---|
| `intent.index` | Intent and amendment files, and the obligations every binding enumerated | Intents: the whole text, owner, worker, criteria with the obligations that check each, gates, children, what each touches; amendments |
| `decision.index` | Decision files | Decision nodes: status, governed names, supersedes |
| `definition.index` | Claimed files | Definitions: name, identity, dependencies, granularity, materialising files |
| `obligation.enumerate` | A binding and its indexed definitions | Obligations: name, specified-by, targets, kind, expectation, planted-defect link, configuration, the files a check may read |
| `obligation.check` | One obligation with its inputs materialised | A run description, or a final verdict with evidence |
| `artifact.build` | A build obligation with its inputs materialised | A run description, or final output identities |
| `conformance.check` | A specification, an implementation or artifact, a mapping | A run description, or a final verdict with method and trusted base |
| `run.submit` | A run description | A handle. Then `run.poll` and `run.cancel` by handle |
| `tool.resolve` | Tool name, constraint, platform | Version, tree digest, requirements, upstream source; on request, the tree |
| `store.blob` | An identity, or a file | A file, or an identity |

## Checks that need tools

Verifiers, builders and conformance checkers never start tools ([decision 0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md)). The exchange is a loop:

1. The kernel sends the obligation.
2. The provider answers `next` with a **run description**, or `final` with a verdict.
3. For `next`, the kernel submits the run to the configured executor, waits for it by handle, and sends the provider the exit status and the output files.
4. Back to step 2.

Every run in the loop is recorded in the evidence. A provider may add declared inputs only before the first run is submitted, because the evidence key is fixed at that point. Every later run in the same check may name only tools and inputs already in the key; anything else ends the check in `error`.

A **run description** (see [messages.schema.json](messages.schema.json)) names: the program as an exact file inside a pinned tool tree, the argument list, the input files, the declared outputs, limits, the target platform, and the tool digests expected. The executor's final report names the platform and tool digests it actually ran; any difference is an `error`.

## Schemas

| File | Describes |
|---|---|
| [common.schema.json](common.schema.json) | Identities, names, platforms, verdicts, status, strength, isolation, capability names |
| [provider-manifest.schema.json](provider-manifest.schema.json) | What a provider announces |
| [evidence-record.schema.json](evidence-record.schema.json) | One evidence entry. Check and conformance records require `strength`. Build records omit it |
| [act-record.schema.json](act-record.schema.json) | One act of judgement, with what is needed to grade how separate the actor was from the work |
| [messages.schema.json](messages.schema.json) | Every line on the wire: hello, the manifest answer, request, result, error and shutdown envelopes; the request and result body of every capability; the run description and the executor's report; what the indexers and enumeration return |
| [project-intent-criteria.schema.json](project-intent-criteria.schema.json) | The decoded `criteria` value in a project intent file, including the ASCII digits in criterion IDs and the required fields for deferred gates |
| [lock.schema.json](lock.schema.json) | The lock: providers and tools pinned to exact versions, one digest and entry point per platform, upstream source, requirement closure |
| [policy.schema.json](policy.schema.json) | What must pass: required obligations and intents, minimum evidence, the gate floor, acceptable providers, executors and record origins, the separation floor per kind of act |
| [status.schema.json](status.schema.json) | The result of the agent-facing `status` command, with its error object and error codes. A passed project report identifies the policy it was judged against |

Two documents sit beside the schemas: the [configuration reference](../docs/configuration.md) for `dodona.toml`, and [writing a provider](../docs/writing-a-provider.md), a walkthrough with a worked session whose every JSON line validates against these schemas.

Written beside the schemas: the [canonical encoding](canonical-encoding.md), the [path check](path-check.md) and the [digest of a tool tree](tool-tree-digest.md), each with test vectors in the conformance kit, and the [ledger file](ledger.md), whose exact bytes the kit holds. Still to be written or decided: the bodies of ledger entries other than evidence and acts (the ledger file keeps an entry of any kind, and a submission or an outcome has no schema), the agent interface beyond `status` (the shapes of `resolve`, `index`, `plan`, `run`, `explain`, `review` and `reproduce`), the file format and location of the lock, the file format of the policy (dodona's own `policy.toml` is TOML with the keys of the policy schema, which is not yet a decision: [configuration](../docs/configuration.md#policy)), and a conformance kit that judges a provider rather than a host. Two seed kernels exist and CI judges both with the conformance kit, but nothing yet validates what a kernel produces against these schemas: the records in the kit are smaller than the schemas describe ([Not yet in the kit](../conformance/README.md#not-yet-in-the-kit)).

## Rules a schema cannot express

Validating a message against its schema is a first filter. The kernel also holds to these, and a breach ends the check or the session in `error`:

- **Wire parsing is as strict as the canonical encoding.** A message with a repeated key, a number that is not an integer, a lone surrogate, or nesting deeper than the limit in `hello` is refused.
- **Every path passes the [path check](path-check.md)**, not only the pattern in the schema. A program path must lie inside the tool tree it names. The same holds for the starting directory of a run and for the path part of a `${tool:NAME}/PATH` argument.
- **A tool is one the provider declared.** A run description that names a tool missing from the provider's manifest, in its program or in an argument, is refused.
- **A run reads what its check is about, and nothing outside.** A run description must list as inputs every file its obligation names, and must target the platform the check was asked for. An argument that contains a character that can start or join a path (`/`, `\`, `~`, `@`, `$`, `%`, or `..`) must be, exactly and as a whole, one of the run's input files or one file of a declared tool. A word that is not a file may hold printable ASCII characters only, so a look-alike of `/` or `..` is refused too. The stage-0 host allows no environment variables, and no output may have the name of an input. So a path hidden inside an option, such as `-config=/etc/passwd` or `-I..`, is refused because of its characters, whatever the option is. A plain word that happens to be the name of some other file cannot be told apart from an option, and whether a run actually reads the files it was given cannot be seen from its description at all; confining the run to its own files is the executor's job.
- **The verdict is the provider's reading.** The host checks that a verdict rests on a run that exited, within the strength declared. Whether exit status 1 means a failure or a violation found as expected is the provider's to say, and a provider that reads it wrongly is wrong in a way no host can see. That is why a provider is part of the trusted base of every result it gives.
- **A run's inputs are in the key.** A run description that lists an input the check was not given is refused.
- **Every file is re-hashed.** The identity a provider gives for a file is recomputed from its bytes.
- **An answer matches its request**: same `id`, same capability, and an `id` that was asked.
- **A verdict rests on a run.** A final `passed` or `failed` with no run behind it is refused.
- **Strength has a ceiling.** A result may not claim a stronger rank than the provider's manifest declares.
- **A run that did not exit ends the check.** A run that timed out, was cancelled or exceeded a limit ends the check in `error`; the provider is not asked to interpret it.
- **Every run uses only what is in the key.** What an earlier run of the same check produced reaches the provider in that run's report, never as an input of a later run ([host rule 9](../conformance/README.md#host-checks-rules-a-schema-cannot-express)).
- **A provider cannot confirm an intent or grant an exception.** Those come only from act records with tickets the kernel issued.
- **Each run of a check is submitted under its own key**, which includes its number, so a repeated run is never answered from an earlier one.

## Tool trees

A tool is pinned as a whole tree. How the digest of a tree is computed, and which trees have none, is in [tool-tree-digest.md](tool-tree-digest.md), with vectors. A check request may carry the listing of a tool tree, and a run may declare a directory as an output. The stage-0 host passes neither yet.

A draft lock entry lists one pin for each exact platform it covers. The offline fixtures check the full platform object, including whether `libc` or `emulated_on` is present. [Draft lock schema](lock.schema.json).

## The ledger

What a kernel records, it appends to one file. The format, what counts as an entry cut short and what counts as damage, and how two kernels take turns, are in [ledger.md](ledger.md). The conformance kit holds the exact bytes.

## Rules for every message

- Paths are relative, use `/`, and pass the normative path check.
- Commands are argument lists. No message carries a string meant for a shell.
- Sets are sorted as the [canonical encoding](canonical-encoding.md) sorts keys, so equal content encodes identically in every language.
- Numbers are integers. No floating point takes part in any identity.
- No wall-clock time takes part in any identity.
