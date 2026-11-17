# Provider protocol

Draft **0.1**. Not implemented, and expected to change before the first kernel exists.

A provider is a separate program ([decision 0003](../decisions/0003-providers-are-separate-processes.md)). The kernel starts it and the two exchange UTF-8 JSON messages, one per line, over standard input and output. Standard error is captured as a log attachment and never interpreted.

## Session

1. The kernel sends `hello` with the protocol versions it speaks.
2. The provider answers with its [manifest](provider-manifest.schema.json): name, version, capabilities, the tools it needs and its trusted base.
3. The kernel sends requests, each with an `id`. The provider answers each with a result or an error carrying the same `id`. The kernel drives; the provider never initiates.
4. The kernel sends `shutdown`, or closes the stream.

A message that fails schema validation, an unknown required field, or a mismatched `id` ends the session. Any check in flight in that session gets verdict `error`.

## Capabilities

| Capability | Request carries | Result carries |
|---|---|---|
| `decision.index` | Decision files | Decision nodes: status, governs, supersedes |
| `definition.index` | Source files | Definitions: identity, dependencies, granularity |
| `artifact.build` | Definitions, target, resolved tools | A run description; after execution, output identities |
| `obligation.check` | Specification and target definitions, resolved tools, configuration | A run description; after execution, a verdict and evidence |
| `conformance.check` | A specification, an implementation, a mapping | A run description; after execution, a verdict, the method and the trusted base |
| `run.execute` | A run description: tool, argument list, input directory, declared outputs, limits | Exit status and outputs, or `unavailable` |
| `tool.resolve` | Tool name, constraint, platform | Exact version and digest; on request, the tool itself |
| `store.blob` | An identity, or bytes | Bytes, or an identity |

Verifiers, builders and conformance checkers never start tools. They return a **run description**, the kernel hands it to the configured executor, and the provider then interprets the outputs ([decision 0007](../decisions/0007-execution-backend-is-separate-from-the-verifier.md)).

## Schemas

| File | Describes |
|---|---|
| [common.schema.json](common.schema.json) | Identities, platforms, the verdict set, relative paths, capability names |
| [provider-manifest.schema.json](provider-manifest.schema.json) | What a provider announces |
| [evidence-record.schema.json](evidence-record.schema.json) | One ledger entry |

Still to be written: request and result messages per capability, the run description, the lock, and the canonical encoding used for hashing.

## Rules for every message

- Paths are relative, use `/`, and are Unicode NFC.
- Commands are argument lists. No message carries a string meant for a shell.
- Lists that represent sets are sorted, so equal content encodes identically.
- No wall-clock time takes part in any identity.
