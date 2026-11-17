# Decisions

dodona's own decisions, written in the default decision format. This directory is dodona used on itself, before dodona exists: the records are real, and the links are checked by hand until a kernel can check them.

## Format

Each record is a Markdown file with a header:

| Field | Meaning |
|---|---|
| `id` | Stable number, never reused |
| `status` | `proposed`, `accepted`, `superseded` or `rejected` |
| `governs` | What the decision constrains. Repository paths for now; definition identities once an index exists |
| `supersedes` | Ids of decisions this one replaces |

`accepted` means the project owner decided it. `proposed` means it is the current design and still open to challenge. An accepted decision may rest on proposed ones for its detail; the accepted part is the direction stated in its title.

To propose a decision, add a record with status `proposed`. Only the project owner changes a status to `accepted`. Until the first public release, records may be revised in place; after it, a change of meaning is always a new record.

After the first release, a record is never edited to change its meaning. A changed decision is a new record that supersedes the old one.

Every record ends with **What would show this wrong**: an observable outcome that would falsify the decision. A decision without one is an opinion.

## Index

| Id | Decision | Status |
|---|---|---|
| [0001](0001-decisions-are-nodes.md) | Decisions are first-class nodes | accepted |
| [0002](0002-small-kernel-everything-else-is-a-provider.md) | Small kernel; everything else is a provider | accepted |
| [0003](0003-providers-are-separate-processes.md) | Providers are separate processes speaking a versioned protocol | proposed |
| [0004](0004-definition-identity-comes-from-the-language-provider.md) | Definition identity comes from the language provider, with a file-level fallback | proposed |
| [0005](0005-closed-verdict-set.md) | A closed set of verdicts; only a pass is a pass | proposed |
| [0006](0006-evidence-key-and-trusted-base.md) | Evidence is reused by key, and the trusted base is listed | proposed |
| [0007](0007-execution-backend-is-separate-from-the-verifier.md) | The execution backend is separate from the verifier | proposed |
| [0008](0008-reproducibility-levels.md) | Reproducibility through a lock, at a level the agent chooses | accepted |
| [0009](0009-platform-order-and-portability-rules.md) | Platform order, and portability rules that apply from day one | accepted |
| [0010](0010-agents-are-the-primary-user.md) | Agents are the primary user | accepted |
| [0011](0011-self-hosting-through-a-verified-seed.md) | Self-hosting through a verified seed; no implementation language is fixed | accepted |
| [0012](0012-spec-to-code-conformance-is-an-explicit-seam.md) | Specification-to-code conformance is an explicit seam | proposed |
| [0013](0013-initial-binding-for-kernel-models.md) | TLA+ is the initial binding for dodona's own kernel models | proposed |
| [0014](0014-policy-is-separate-from-configuration.md) | Policy is separate from configuration | proposed |
| [0015](0015-ledger-integrity-and-record-trust.md) | Ledger integrity, and trust in records from elsewhere | proposed |
| [0016](0016-provider-isolation-is-stated-not-assumed.md) | Provider isolation is stated, not assumed | proposed |
