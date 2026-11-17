# Conformance kit

Not yet written. This is stage 1 of [the bootstrap](../ARCHITECTURE.md#7-building-dodona-with-dodona), and it comes before any kernel.

The kit is data, independent of every implementation, in two parts.

**For kernels.** Scenarios as input and expected output: a project state, a sequence of events (edits, tool changes, submissions, completions, outages), and the status the kernel must report afterwards. Scenarios are derived from the formal models, including the counterexample traces of each planted defect, so a kernel that repeats a modelled defect fails a named scenario.

**For providers.** Per capability: fixed inputs with required results, malformed-message cases that must end in `error`, and determinism cases that run the same request twice and on two platforms.

**Vectors.** Pure-function test data that needs no second machine: the canonical encoding, the path check (reserved names, non-NFC names, case-fold collisions, trailing dots, over-long paths), line-ending and byte-order-mark cases, and argument lists that are hard to pass without a shell. Hostile names and bytes are stored as escaped data inside the vectors, never as real files, so the kit can be checked out on every platform.

**A misbehaving provider.** A test provider that deliberately emits carriage returns, a byte-order mark, a wrong encoding, an over-long line, a flood on standard error, a late answer and a child process that never exits. A kernel must end each case in `error` and clean up.

Rules for the kit:

- A scenario is added before the behaviour it tests.
- Every check in the kit has a planted defect that makes it fail. A check that has never been seen to fail is not counted.
- Adversarial scenarios are written without looking at any implementation.
- The kit's own adequacy is measured: kernels with known defects are run against it, and the fraction it rejects is reported.
- Two kernels that both pass the whole kit and still disagree on some input mean the kit is missing a scenario; the disagreement becomes one.
