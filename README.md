# dodona

Tooling for building software where the code, the proof that it is correct, and the reason it exists stay linked.

> In the myth, the Argo carried a beam of oak from Dodona in its prow. The beam could speak, and it told the crew the truth.

**Status:** design stage. There is an architecture, decision records, a first formal model and draft protocol schemas. There is no kernel and nothing to run yet.

## The idea

Three things usually live apart and drift: the decision record that explains why something was built, the formal specification that says what it must do, and the code that does it. dodona keeps them connected:

- **Decision records as first-class nodes.** Each architecture decision record (ADR) links to the definitions it governs by content hash, and keeps its supersedes history. When a definition changes, the decisions that depend on it are known.
- **Formal verification.** Behaviour is specified formally and checked by a machine, by model checking or proof, instead of relying on tests alone.
- **A compiled language.** The implementation is compiled, with pure state transitions at the core and effects kept at the edges.
- **Selective reruns.** Definitions are content-addressed, so a check or proof runs again only when something it depends on has changed.

## Design

- **The user is an agent.** dodona is driven by AI agents through structured commands; people read the results.
- **Nothing is built in.** The decision format, specification language, checker, compiler and the place checks run are all replaceable providers, and a project can mix them.
- **Only a pass is a pass.** A check that was queued, timed out or could not start is reported as exactly that.
- **Reproducible across platforms.** A committed lock pins every tool by digest per platform. macOS first, then Linux, then Windows.
- **Built with itself.** dodona's own decisions and formal specification are the source of truth; an implementation is a derived artefact that must conform to them.

Start with [ARCHITECTURE.md](ARCHITECTURE.md). The reasons are in [decisions/](decisions/README.md), the formal models and what they do and do not show are in [spec/](spec/README.md), and the provider protocol is in [protocol/](protocol/README.md). Agents working here follow [AGENTS.md](AGENTS.md).

## Licence

[MIT](LICENSE)
