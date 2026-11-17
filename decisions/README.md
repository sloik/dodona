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
| `direction` | Optional. `owner` when the project owner set the direction |

`accepted` means the project owner has read the record and decided it. `proposed` means it is the current design and still open to challenge. No record is accepted yet.

`direction: owner` in the header marks a proposed record whose direction, as stated in its title, was given by the project owner. The detail in the body is still a proposal.

To propose a decision, add a record with status `proposed`. Only the project owner changes a status to `accepted`. Until the first public release, records may be revised in place; after it, a change of meaning is always a new record.

After the first release, a record is never edited to change its meaning. A changed decision is a new record that supersedes the old one.

Every record ends with **What would show this wrong**: an observable outcome that would falsify the decision. A decision without one is an opinion.

## Index

| Id | Decision | Status |
|---|---|---|
| [0001](0001-decisions-are-nodes.md) | Decisions are first-class nodes | proposed, owner direction |
| [0002](0002-small-kernel-everything-else-is-a-provider.md) | Small kernel; everything else is a provider | proposed, owner direction |
| [0003](0003-providers-are-separate-processes.md) | Providers are separate processes speaking a versioned protocol | proposed |
| [0004](0004-definition-identity-comes-from-the-language-provider.md) | Definition identity comes from the language provider, with a file-level fallback | proposed |
| [0005](0005-closed-verdict-set.md) | A closed set of verdicts; only a pass is a pass | proposed |
| [0006](0006-evidence-key-and-trusted-base.md) | Evidence is reused by key, and the trusted base is listed | proposed |
| [0007](0007-execution-backend-is-separate-from-the-verifier.md) | The execution backend is separate from the verifier | proposed |
| [0008](0008-reproducibility-levels.md) | Reproducibility through a lock, at a level the agent chooses | proposed, owner direction |
| [0009](0009-platform-order-and-portability-rules.md) | Platform order, and portability rules that apply from day one | proposed, owner direction |
| [0010](0010-agents-are-the-primary-user.md) | Agents are the primary user | proposed, owner direction |
| [0011](0011-self-hosting-through-a-verified-seed.md) | Self-hosting through a verified seed; no implementation language is fixed | proposed, owner direction |
| [0012](0012-spec-to-code-conformance-is-an-explicit-seam.md) | Specification-to-code conformance is an explicit seam | proposed |
| [0013](0013-initial-binding-for-kernel-models.md) | TLA+ is the initial binding for dodona's own kernel models | proposed |
| [0014](0014-policy-is-separate-from-configuration.md) | Policy is separate from configuration | proposed |
| [0015](0015-ledger-integrity-and-record-trust.md) | Ledger integrity, and trust in records from elsewhere | proposed |
| [0016](0016-provider-isolation-is-stated-not-assumed.md) | Provider isolation is stated, not assumed | proposed |
| [0017](0017-intent-in-plain-words-broken-down.md) | Work starts as intent in plain words, and breaks down | proposed, owner direction |
| [0018](0018-hard-soft-and-deferred-gates.md) | Hard, soft and deferred gates | proposed, owner direction |
| [0019](0019-assurance-is-stated-per-link.md) | Assurance is stated for each link, and the weakest link is the score | proposed, owner direction |
| [0020](0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md) | Exceptions are granted by the intent owner, and recorded | proposed, owner direction |
| [0021](0021-dodona-judges-and-does-not-plan.md) | dodona judges; it does not plan or do the work | proposed, owner direction |
| [0022](0022-open-project-published-as-it-evolves.md) | An open project, published as it evolves | proposed, owner direction |
| [0023](0023-stage-0-checks-run-in-ci-with-disposable-helpers.md) | Stage-0 checks run in CI, with disposable helpers | proposed, owner direction |
| [0024](0024-separation-is-graded-not-enforced.md) | Separation of the checker from the work is graded, not enforced | proposed, owner direction |
