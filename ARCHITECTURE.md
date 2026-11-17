# dodona architecture

Status: **draft 0.1**. Nothing in this document is implemented. Where a claim has a formal model, the [claims table](spec/CLAIMS.md) says whether a model checker has actually run on it.

Each numbered decision behind this document is recorded in [`decisions/`](decisions/README.md). This file is the overview; when the two disagree, the decision record wins.

## 1. What dodona is

dodona keeps four things linked and tells an agent which of them are still true:

1. **Decisions**: why something exists, what was rejected, what it replaces.
2. **Specifications**: what must hold, stated formally.
3. **Definitions**: the code, down to the smallest unit the language can identify.
4. **Evidence**: recorded results of checking definitions against specifications.

When anything changes, dodona works out which evidence is no longer valid, reruns only those checks, and reports what is now proven, failing or unknown.

**The user is an agent.** People read the output, but the interface is designed for a program driving it: structured input and output, stable error codes, no prompts, no prose that has to be parsed ([0010](decisions/0010-agents-are-the-primary-user.md)).

**dodona chooses no tools.** The decision format, the specification language, the checker, the compiler and the place a check runs are all replaceable parts, and a project can mix them freely ([0002](decisions/0002-small-kernel-everything-else-is-a-provider.md)).

## 2. Shape

```
                    agent
                      │  structured commands and results
              ┌───────▼────────┐
              │     kernel     │  graph · identity · planner · evidence ledger
              └───────┬────────┘
                      │  provider protocol (versioned messages between processes)
   ┌──────────┬───────┼────────┬───────────┬───────────┬───────────┐
decision   language  verifier  conformance  executor   toolchain    store
provider   provider  provider   provider    provider   provider    provider
```

The **kernel** is small and has no knowledge of any language or tool. It owns:

| Part | Responsibility |
|---|---|
| Graph | Content-addressed nodes (decisions, specifications, definitions, obligations, evidence, tools) and typed edges between them |
| Identity | How anything is hashed, so the same input has the same identity on every platform |
| Resolver | Turns the project configuration into a lock: exact providers, exact tools, exact digests per platform |
| Planner | Given the graph and the ledger, decides which obligations are stale and in what order to run them |
| Ledger | Append-only record of every check that ran, with everything it depended on |
| Provider host | Starts providers, negotiates capabilities, validates every message against the protocol |
| Agent interface | The only way in: commands with structured input and output |

Everything else is a **provider**: a separate program that speaks the [provider protocol](protocol/README.md) ([0003](decisions/0003-providers-are-separate-processes.md)).

## 3. Provider kinds

A provider implements one or more *capabilities*. Capabilities are the unit of mixing: a project may take definition indexing from one provider and building from another.

| Kind | Capability | Supplies | Examples (none shipped yet) |
|---|---|---|---|
| Decision | `decision.index` | Decision nodes from files: status, what each governs, what it supersedes | Markdown ADR, a formal decision language |
| Language | `definition.index` | Definitions with identity and dependency edges, at the granularity the language allows | Per-definition for Unison or Dafny, per-file fallback |
| Language | `artifact.build` | Build outputs for a target, plus whether the output is deterministic | Dafny to Go, a C compiler |
| Verifier | `obligation.check` | A verdict and evidence for one obligation | TLC, Dafny verifier, a test runner |
| Conformance | `conformance.check` | Evidence that an implementation matches a specification, with its trusted base | Trace replay, refinement proof |
| Executor | `run.execute` | A place for a tool to run, returning output or `unavailable` | Local process, remote queue, container |
| Toolchain | `tool.resolve` | An exact, digest-pinned tool for each platform | Release download, system package set |
| Store | `store.blob` | Storage for evidence and build outputs | Local directory, shared remote |

Three seams deserve attention because they are easy to blur:

- **Verifier and executor are different providers** ([0007](decisions/0007-execution-backend-is-separate-from-the-verifier.md)). "Check this model with TLC" and "run it on that machine" are separate choices. One project runs the checker locally, another sends it to a queue, and neither changes the verifier.
- **Conformance is its own seam** ([0012](decisions/0012-spec-to-code-conformance-is-an-explicit-seam.md)). A verified specification says nothing about code unless something connects them. dodona makes that connection a first-class obligation with a stated trusted base, so "the model passes" can never be read as "the code is correct".
- **Tests are verifiers.** A test suite is an `obligation.check` provider with weaker evidence than a proof. The evidence class is recorded, never flattened.

## 4. Identity

Everything hangs on identity ([0004](decisions/0004-definition-identity-comes-from-the-language-provider.md)).

- A **definition** is whatever unit the language provider can name and hash: a function, a lemma, a module, or a whole file. The provider returns the identity, the definitions it depends on, and the granularity it achieved.
- If no provider claims a file, the kernel falls back to **file identity**: the hash of the bytes. This is always correct and merely coarse: more reruns, never a wrong reuse.
- A **decision** links to definitions by identity. When a governed definition changes, the decision is flagged for review; it does not silently keep pointing at something that no longer exists.

Hashing rules are fixed by the kernel so that identity does not depend on the platform ([0009](decisions/0009-platform-order-and-portability-rules.md)):

- File content is hashed as raw bytes. Projects enforce one line-ending convention in version control; the kernel reports a file whose line endings differ from the declared convention as an error instead of normalising it.
- Paths are relative to the project root, use `/`, are Unicode NFC, and are compared case-sensitively. Two paths that differ only by case, and names a supported platform cannot represent, are rejected at index time.
- Structured values are hashed over one canonical encoding defined in the protocol.
- The hash algorithm is named in every identity, so it can be replaced.

## 5. Verdicts and evidence

A check ends in exactly one verdict ([0005](decisions/0005-closed-verdict-set.md)):

| Verdict | Meaning | Reusable |
|---|---|---|
| `passed` | The check ran to completion and the obligation holds | Yes |
| `failed` | The check ran to completion and the obligation does not hold; a counterexample or diagnostic is attached | Yes |
| `pending` | Submitted, not finished | No |
| `unavailable` | The executor or a tool could not be reached | No |
| `error` | The check did not complete: crash, timeout, cancelled, malformed output | No |
| `unsupported` | The provider cannot express or check this obligation | No |

Only `passed` is ever a pass. Nothing converts any other verdict into one, and an obligation with no reusable record for its current key is reported as unknown.

Every record carries an **evidence key**: a hash over everything the result depends on ([0006](decisions/0006-evidence-key-and-trusted-base.md)):

- the identities of the obligation's specification and target definitions, with their full dependency closure
- the provider's identity and version, and the protocol version
- the resolved digests of every tool it used
- its configuration: bounds, flags, seeds
- the platform, unless the provider declares the result platform-independent
- any further inputs the provider declares

A record is reused only when its key equals the key computed now. The key is fixed when the check is submitted, from an immutable snapshot of the inputs, and the result is recorded under that key even if the project changed while the check ran.

This rule is sound only under stated assumptions, which together form the **trusted base**. dodona lists them instead of hiding them:

- a provider reports every input its result depends on
- a provider's verdict is correct for the inputs it was given
- the hash function does not collide
- the executor runs the tool it was asked to run

Each provider declares its own additions to the trusted base, and every reported result can be traced to the full list it rests on.

## 6. Reproducibility

Reproducing a project on another machine means resolving the same lock and getting the same answers ([0008](decisions/0008-reproducibility-levels.md)).

- **Configuration** says what the project wants: providers, tools, version ranges, policies. It contains no absolute paths, no shell fragments and no platform-specific values outside explicitly labelled per-platform sections. Commands are argument lists, never strings for a shell.
- **The lock** says what that resolved to: for every provider and tool, the exact version and one digest per platform. The lock is generated, committed, and identical on all platforms. Adding a platform adds entries; it never changes existing ones.
- **The level is chosen by the agent**, per obligation or build target:

| Level | Guarantee |
|---|---|
| `verdict` (default) | Same lock and sources give the same verdict on every platform |
| `evidence` | Additionally, the recorded evidence summary is equal, for example the same number of states explored |
| `artifact` | Additionally, build outputs are byte-identical; allowed only where the provider declares it can do this |

A level a provider cannot meet is a configuration error at resolve time, not a surprise later. Disagreement between two platforms at the chosen level is itself reported as a `failed` reproducibility obligation.

Platforms are supported in a fixed order: macOS, then Linux, then Windows, then others. Portability is designed in from the start instead of patched in later; the rules in [0009](decisions/0009-platform-order-and-portability-rules.md) apply now, on the first platform.

## 7. Building dodona with dodona

No implementation language is chosen ([0011](decisions/0011-self-hosting-through-a-verified-seed.md)). The source of truth for dodona is its own decisions and its own formal specification, kept in this repository in dodona's own formats. An implementation is a *derived artefact*: it is accepted because it conforms to the specification, and it can be replaced by another one in a different language that also conforms.

| Stage | What exists | How it is checked |
|---|---|---|
| 0 (now) | Decisions, protocol schemas, formal models of the kernel | Model checker run by hand through any executor |
| 1 | Conformance kit: scenario corpus and planted defects, independent of any implementation | Every planted defect is rejected by the checks it targets |
| 2 | **Seed**: a first kernel, in whatever language the chosen providers support | Passes the conformance kit and the specification conformance obligation |
| 3 | dodona checks dodona: the seed runs dodona's own obligations | The repository's own configuration resolves and all obligations pass |
| 4 | dodona builds dodona: the seed builds the next kernel, which rebuilds itself | The two builds agree at the chosen reproducibility level |
| 5 | Second, independent kernel from the same specification | Both kernels agree on the whole conformance kit |

The seed is pinned by digest in the lock like any other tool. Stage 5 is what keeps the bootstrap honest: a defect hidden in one seed has to survive comparison with an implementation that shares none of its code.

## 8. Repository layout

```
ARCHITECTURE.md     this document
AGENTS.md           rules for agents working in this repository
dodona.toml         dodona's own project configuration (not yet executable)
decisions/          decision records, in the default decision format
protocol/           provider protocol: message and record schemas
spec/               formal models of the kernel, and the claims table
conformance/        scenario corpus and planted defects for kernels and providers
providers/          reference providers (empty until stage 2)
```

There is deliberately no source tree for the kernel yet.

## 9. What makes this verifiable

An architecture claim counts only if something can show it false. Each claim in [`spec/CLAIMS.md`](spec/CLAIMS.md) names:

- the property, stated precisely
- how it is checked: a model property, a conformance scenario, or a falsifiable consequence in a decision record
- a **planted defect** that must make the check fail, so a check that cannot fail is not counted as passing
- its status: `modelled, unchecked`, `checked` with a reference to the run, or `not yet modelled`

## 10. Open questions

- The canonical encoding for structured hashing, and the default hash algorithm.
- Whether providers may also be loaded as sandboxed modules, in addition to separate processes.
- How decisions written in a formal language express "governs" and "supersedes".
- How a provider proves its declared inputs are complete, instead of being trusted on it.
- The sandbox a provider runs in, and what it may read.
