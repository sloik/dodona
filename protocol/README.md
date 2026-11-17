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

A message that fails validation, a missing required field, or a mismatched `id` ends the session; any check in flight in it gets verdict `error`. An answer that arrives after its deadline is logged and dropped.

## Capabilities

| Capability | Request carries | Result carries |
|---|---|---|
| `intent.index` | Intent and amendment files | Intents: owner, criteria, gates, children, what each touches; amendments |
| `decision.index` | Decision files | Decision nodes: status, governed names, supersedes |
| `definition.index` | Claimed files | Definitions: name, identity, dependencies, granularity, materialising files |
| `obligation.enumerate` | A binding and its indexed definitions | Obligations: name, specified-by, targets, kind, expectation, planted-defect link, configuration |
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

A **run description** names: the program as an exact file inside a pinned tool tree, the argument list, the input files, the declared outputs, limits, the target platform, and the tool digests expected. The executor's final report names the platform and tool digests it actually ran; any difference is an `error`.

## Schemas

| File | Describes |
|---|---|
| [common.schema.json](common.schema.json) | Identities, names, platforms, verdicts, status, strength, isolation, capability names |
| [provider-manifest.schema.json](provider-manifest.schema.json) | What a provider announces |
| [evidence-record.schema.json](evidence-record.schema.json) | One ledger entry |

Still to be written: request and result messages per capability, the run description, the submission and outcome ledger entries, the lock, policy, the configuration reference, the canonical encoding with its test vectors, the normative path check with its test vectors, and the agent interface.

## Rules for every message

- Paths are relative, use `/`, and pass the normative path check.
- Commands are argument lists. No message carries a string meant for a shell.
- Sets are sorted by UTF-8 bytes, so equal content encodes identically in every language.
- Numbers are integers. No floating point takes part in any identity.
- No wall-clock time takes part in any identity.
