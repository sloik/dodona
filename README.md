# dodona

Tooling for building software where the code, the proof that it is correct, and the reason it exists stay linked.

> In the myth, the Argo carried a beam of oak from Dodona in its prow. The beam could speak, and it told the crew the truth.

**Status:** just started. Nothing here is usable yet, and the design is still open.

## The idea

Three things usually live apart and drift: the decision record that explains why something was built, the formal specification that says what it must do, and the code that does it. dodona keeps them connected:

- **Decision records as first-class nodes.** Each architecture decision record (ADR) links to the definitions it governs by content hash, and keeps its supersedes history. When a definition changes, the decisions that depend on it are known.
- **Formal verification.** Behaviour is specified formally and checked by a machine, by model checking or proof, instead of relying on tests alone.
- **A compiled language.** The implementation is compiled, with pure state transitions at the core and effects kept at the edges.
- **Selective reruns.** Definitions are content-addressed, so a check or proof runs again only when something it depends on has changed.

## Open questions

The foundation is not chosen. Two candidates are being compared against the same contract:

| Track | Specification and proof | Implementation |
|---|---|---|
| A | TLA+ | Unison |
| B | Dafny | Dafny, compiled to Go and JavaScript |

A per-module mix of the two, or a third option, is an allowed outcome.

## Licence

[MIT](LICENSE)
