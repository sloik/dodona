# dodona architecture

Status: **draft 0.2**. Nothing in this document is implemented. Draft 0.1 was reviewed by five independent reviewers; what they found and what changed is in [docs/reviews/](docs/reviews/2026-11-17-draft-0.1.md). Where a claim has a formal model, the [claims table](spec/CLAIMS.md) says whether a model checker has actually run on it.

The decisions behind this document are recorded in [`decisions/`](decisions/README.md). No decision is accepted yet: all are proposals, and those marked `direction: owner` follow a direction the project owner gave. Once a decision is accepted it overrides this file. Terms are defined in [the data model](MODEL.md).

## 1. What dodona is

dodona keeps four things linked and tells an agent which of them are still true:

1. **Decisions**: why something exists, what was rejected, what it replaces.
2. **Specifications**: what must hold, stated formally.
3. **Definitions**: the code, down to the smallest unit the language can identify.
4. **Evidence**: recorded results of checking definitions against specifications.

When anything changes, dodona works out which evidence is no longer valid, reruns only those checks, and reports what is now proven, failing or unknown.

**The user is an agent.** People read the output, but the interface is designed for a program driving it: structured input and output, stable error codes, no prompts, no prose that has to be parsed ([0010](decisions/0010-agents-are-the-primary-user.md)).

**dodona chooses no tools.** The decision format, the specification language, the checker, the compiler and the place a check runs are all replaceable parts, and a project can mix them freely ([0002](decisions/0002-small-kernel-everything-else-is-a-provider.md)).

**The agent being judged does not set the bar.** What must pass, and how strongly, is held in a policy the working agent cannot quietly change ([0014](decisions/0014-policy-is-separate-from-configuration.md)).

## 2. Shape

```
                    agent
                      │  structured commands and results
              ┌───────▼────────┐
              │     kernel     │  graph · identity · planner · ledger · policy
              └───────┬────────┘
                      │  provider protocol (versioned messages between processes)
   ┌──────────┬───────┼────────┬───────────┬───────────┬───────────┐
decision   language  verifier  conformance  executor   toolchain    store
provider   provider  provider   provider    provider   provider    provider
```

The **kernel** is small and has no knowledge of any language or tool. It owns:

| Part | Responsibility |
|---|---|
| Graph | Nodes and typed edges, as defined in [the data model](MODEL.md) |
| Identity | How anything is hashed and how paths are validated, identically on every platform |
| Resolver | Turns configuration into a lock: exact providers and tools, with digests per platform |
| Planner | Decides which obligations are stale and in what order to run them |
| Ledger | Durable, single-writer, append-only record of every check that ran |
| Policy | What is required to pass, compared against what actually passed |
| Provider host | Starts providers, bounds them, validates every message |
| Agent interface | The only way in: [commands](MODEL.md#6-agent-interface) with structured input and output |

Everything else is a **provider**: a separate program that speaks the [provider protocol](protocol/README.md) ([0003](decisions/0003-providers-are-separate-processes.md)).

## 3. Provider kinds

A provider implements one or more *capabilities*. Capabilities are the unit of mixing: configuration binds each capability separately, so a project may take definition indexing from one provider and building from another.

| Kind | Capability | Supplies |
|---|---|---|
| Decision | `decision.index` | Decision nodes: status, what each governs (by name), what it supersedes |
| Language | `definition.index` | Definitions: stable name, content identity, dependencies, and the files that materialise them |
| Language | `artifact.build` | Build outputs as graph nodes, and whether the output is deterministic |
| Verifier, language, conformance | `obligation.enumerate` | The obligations a binding gives rise to, each with a stable name. Required of any provider that checks, builds or tests conformance |
| Verifier | `obligation.check` | A verdict and evidence for one obligation |
| Conformance | `conformance.check` | Evidence that an implementation matches a specification, with method and trusted base |
| Executor | `run.submit` | A place for a tool to run: submit, poll, cancel; reports what actually ran and where |
| Toolchain | `tool.resolve` | An exact tool tree for a platform, with its digest and what it requires |
| Store | `store.blob` | Storage for attachments and build outputs |

Seams that are easy to blur, and are kept apart on purpose:

- **Verifier and executor are different providers** ([0007](decisions/0007-execution-backend-is-separate-from-the-verifier.md)). "Check this model with this tool" and "run it on that machine" are separate choices. A verifier never starts a tool; it describes runs, and the kernel hands them to the configured executor. A check may need several runs in sequence; the provider returns either the next run or a final result, and every run is recorded.
- **Conformance is its own seam** ([0012](decisions/0012-spec-to-code-conformance-is-an-explicit-seam.md)). A verified specification says nothing about code unless something connects them. That connection is a first-class obligation with a stated method and trusted base. A build step between a verified source and a running binary is part of that chain and is recorded as such.
- **Tests are verifiers.** A test suite is an `obligation.check` provider with weaker evidence than a proof. The evidence class is always recorded and always shown.

## 4. Identity

Everything hangs on identity ([0004](decisions/0004-definition-identity-comes-from-the-language-provider.md)).

- A **definition** has two things: a stable **name** (a path or symbol that survives edits) and a content **identity** (a hash that changes with every edit). A change is "the identity behind this name changed". Without the name, an edit in a content-addressed language would be indistinguishable from a deletion plus an unrelated addition.
- Granularity is whatever the language provider can achieve: definition, module or file. If no provider claims a file, the kernel uses **file identity**: the hash of the bytes. Coarse identity causes extra reruns. It must never cause a wrong reuse.
- A **decision** links to definitions by name and records the identity it was written against. When that identity changes, the decision is flagged for review.
- A **tool** is a directory tree. Its digest is the hash of a canonical listing of the tree, so the same tool has the same digest however it was packaged. A tool declares what it requires (a checker that needs a language runtime requires that runtime), and the whole closure is pinned.

The rules are fixed by the kernel so identity cannot depend on the platform ([0009](decisions/0009-platform-order-and-portability-rules.md)):

- File content is hashed as raw bytes. The project declares its line-ending and byte-order-mark convention; a text file that violates it is an error, never silently normalised. Which files are text is declared by the provider that claims them.
- Paths pass one normative check, listed once in [decision 0009](decisions/0009-platform-order-and-portability-rules.md) and published with test vectors. A path is accepted on every platform or on none.
- Symbolic links and similar indirections inside a project are rejected at index time. File modes never take part in identity.
- Structured values are hashed over one canonical encoding: keys and sets in UTF-8 byte order, integers only, no floating point.
- The algorithm is named in every identity and fixes the digest length.

## 5. Verdicts, status and evidence

A **check** is one attempt to decide an obligation. It is made of one or more tool **runs** and ends in exactly one verdict ([0005](decisions/0005-closed-verdict-set.md)):

| Verdict | Meaning | Reusable |
|---|---|---|
| `passed` | The check ran to completion and found what the obligation expects: the property holds, or for a planted defect, the violation was found | Yes |
| `failed` | The check ran to completion and found the opposite of what the obligation expects, or met the expectation only by relying on something policy does not allow | Yes |
| `pending` | Submitted, not finished | No |
| `unavailable` | The executor or a tool could not be reached | No |
| `error` | The check did not complete or could not decide: crash, timeout, cancelled, malformed output, tool answered "unknown" | No |
| `unsupported` | The provider cannot express or check this obligation, or no pinned tool exists for the executing platform | No |

An **obligation's status** is derived by the kernel from the ledger, never supplied by a provider:

| Status | When |
|---|---|
| `passed` | Records for the current evidence key exist and all reusable ones are `passed` |
| `failed` | Records for the current key exist and all reusable ones are `failed` |
| `conflict` | The current key has both `passed` and `failed` records. Treated as not passed |
| `unknown` | No reusable record for the current key. The reason is given: never run, pending, unavailable, error, unsupported |

Only `passed` is ever a pass. Nothing converts anything else into one, and a pass never outranks a failure recorded for the same inputs.

A **project's status** is relative to policy. It is `passed` only when the policy names at least one required obligation and every required obligation is `passed` on every platform it is required on, at the strength, non-vacuity and isolation policy demands; the full rule is in [the data model](MODEL.md#4-status). A project where nothing was required, or nothing ran, is not green; it is `nothing-required` or `unknown`.

Every record carries an **evidence key** ([0006](decisions/0006-evidence-key-and-trusted-base.md)), in two parts:

- the **core key**, a hash over a published structure: the obligation and what it expects (`holds` or `violated`), the identities of its specification and target definitions with their dependency closure, input artifacts and the obligation that produced them, the provider identity and protocol version, the digests of every tool in the closure, and the configuration: bounds, flags, seeds, worker counts and limits
- the **platform the check actually executed on**, as reported by the executor

The kernel computes the key; providers never do. It is fixed at submission from an immutable copy of the inputs, and the result is filed under it even if the project changed during the run. Status is always asked **for a platform**. Policy names the platforms on which an obligation is required; by default it is the platform of the executor bound to it. A record counts towards an obligation's status on a platform only when its core key equals the core key computed now and its platform is that platform. Keeping the platform outside the core key is what lets the kernel pair records from different platforms and compare them.

There is one exception, and it is explicit: where a provider's claim to be platform-independent has been verified, meaning the same core key has been checked on at least two platforms with agreeing results and policy accepts that, a record from another platform may stand in. The status then says so, naming the platform the record came from.

Every record, including every pass, also carries the exit status and the digest of the raw output it was derived from, so any verdict can be audited later.

Reuse is sound only under stated assumptions, the **trusted base**. dodona lists them instead of hiding them, at three levels: the kernel's own ([MODEL.md](MODEL.md#5-trusted-base)), each provider's standing additions in its manifest, and anything a particular result additionally rests on, such as an axiom a proof used.

## 6. Reproducibility

Reproducing a project on another machine means resolving the same lock and getting the same answers ([0008](decisions/0008-reproducibility-levels.md)).

- **Configuration** states intent: bindings, tools, version ranges. It has no absolute paths, no shell fragments, and no platform-specific values outside labelled per-platform sections.
- **The lock** pins every provider and tool tree to an exact version, with one digest per platform, the upstream source the digest was verified against, and the tool's requirements. It is generated, committed, identical on all platforms, and replaced atomically. Adding a platform adds entries and never changes existing ones.
- **The executor attests.** A run names the platform it targets and the tool digests it expects. The executor reports the platform and digests it actually ran. A mismatch is an `error`, never a result.
- **The level is chosen by the agent**, per obligation or build target, with a default per binding:

| Level | Guarantee |
|---|---|
| `verdict` (default) | Same lock and sources give the same verdict on every platform |
| `evidence` | Additionally, the provider's declared comparable summary is equal, for example the number of states explored |
| `artifact` | Additionally, build outputs are byte-identical; allowed only where the provider declares it can do this |

A level a provider cannot meet is an error at resolve time. Records with the same core key and different platforms are compared at the chosen level; disagreement is a `failed` reproducibility obligation. If only one platform has run, reproducibility is `unknown`, not assumed. A provider's claim to be platform-independent removes nothing from the key; it only allows the stand-in described in section 5, after the claim has itself been checked on two platforms.

Platforms are supported in a fixed order: macOS, then Linux, then Windows, then others. The portability rules in [0009](decisions/0009-platform-order-and-portability-rules.md) apply now, and are tested now with data-only vectors that need no second machine.

## 7. Integrity

A reported pass is worth only as much as the path it took ([0015](decisions/0015-ledger-integrity-and-record-trust.md), [0016](decisions/0016-provider-isolation-is-stated-not-assumed.md)).

- **The ledger has one writer at a time.** Entries are framed and checksummed; a torn final entry is detected, discarded and reported. The kernel reports only what is durably recorded.
- **Submissions are journalled before they are sent.** The ledger holds three kinds of entry: a submission with its key and, once known, the executor's handle; an evidence record for a `passed` or `failed` result; and an outcome entry for anything else. After a restart the kernel reattaches to open submissions by handle instead of submitting again.
- **A record's key is recomputed from its stated inputs whenever it is read.** A record whose key does not match is rejected.
- **Records have an origin.** Records this kernel wrote are trusted. Records arriving from anywhere else, such as a shared store, are not reusable until policy names their origin as trusted and their signature verifies.
- **Providers are bounded.** Every request has a deadline on a monotonic clock, and message and log sizes are capped. A late answer is logged and dropped.
- **Isolation is stated, not assumed.** Each platform offers a different ability to confine a process. Every record states the isolation level its providers and tools ran under: `enforced`, `best-effort` or `none`. Policy can require a level.

## 8. Building dodona with dodona

No implementation language is chosen ([0011](decisions/0011-self-hosting-through-a-verified-seed.md)). The source of truth for dodona is its own decisions and its own formal specification, kept in this repository in dodona's own formats. An implementation is a *derived artifact*: it is accepted because it conforms to the specification, and it can be replaced by another one in a different language that also conforms.

| Stage | What exists | What it establishes |
|---|---|---|
| 0 (now) | Decisions, protocol schemas, formal models of the kernel | Design properties, for the bounds checked |
| 1 | Conformance kit: scenarios and planted defects, independent of any implementation | A way to judge a kernel that is not the kernel |
| 2 | **Seed**: a first kernel, in whatever language the chosen providers support | That this kernel passes the kit and its conformance obligation |
| 3 | The seed runs dodona's own obligations | That dodona can describe itself. No added trust in the seed |
| 4 | The seed builds its successor, which rebuilds itself | That the build is reproducible. No added trust in the seed |
| 5 | A second kernel built independently from the same specification | That a defect must exist in both to go unnoticed |

The trust in this chain is stated plainly:

- The first seed is trusted because its source and build were reviewed, and its provenance is recorded: who built it, from which commit, with which tools. It is pinned by digest in the lock like any other tool.
- A kernel checking itself cannot raise trust in itself. Stages 3 and 4 show capability and reproducibility only.
- Stage 5 helps only as far as the two kernels are independent: different language, different libraries for parsing and hashing, different authors, and where agents write them, different model families. Two kernels that misread the same ambiguous sentence the same way will agree and both be wrong. That residual risk is reduced by making the specification executable as scenarios, and is never zero.
- When two kernels disagree, the status is `conflict`. The more optimistic answer is never taken.

## 9. Repository layout

```
ARCHITECTURE.md     this document
MODEL.md            data model, status rules, trusted base, agent interface
AGENTS.md           rules for agents working in this repository
dodona.toml         dodona's own project configuration (not yet executable)
decisions/          decision records, in the default decision format
protocol/           provider protocol: message and record schemas
spec/               formal models of the kernel, and the claims table
conformance/        scenarios, vectors and planted defects for kernels and providers
providers/          reference providers (empty until stage 2)
docs/reviews/       review rounds: findings and what was done about each
```

There is deliberately no source tree for the kernel yet.

## 10. What makes this verifiable

An architecture claim counts only if something can show it false. Each claim in [`spec/CLAIMS.md`](spec/CLAIMS.md) names:

- the property, stated precisely
- how it is checked: a model property, a conformance scenario, or a falsifiable consequence in a decision record
- a **planted defect** that must make the check fail, so a check that cannot fail is not counted as passing
- its status: `checked` with a reference to the run, `modelled, unchecked`, or `not yet modelled`

The same rule is part of the product: an obligation can carry planted defects, and its status reports whether each was caught.

## 11. Open questions

- How policy is protected from the agent it constrains: a signature, a separate repository, or review of every change.
- The signing scheme for records shared between machines.
- Whether providers may also be loaded as sandboxed modules, in addition to separate processes.
- How decisions written in a formal language express "governs" and "supersedes".
- How a provider's declared inputs can be checked for completeness instead of trusted.
- Whether tools that exist only as installers can be supported at all, beyond a weaker "measured after install" class.
