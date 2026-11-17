# Working in this repository

dodona is built by agents, for agents. These rules bind anyone, human or model, who changes this repository.

1. **Read first:** [ARCHITECTURE.md](ARCHITECTURE.md), then [decisions/README.md](decisions/README.md).
2. **A change of direction is a decision record.** Do not edit an accepted record to change its meaning; add a new one that supersedes it. Only the project owner moves a record to `accepted`.
3. **Specification before implementation.** No kernel or provider code is added without the model property or conformance scenario that judges it, and a planted defect showing the check can fail.
4. **Only a pass is a pass.** Never describe anything as verified, checked or passing unless the check ran to completion and the run is recorded. A check that is queued, timed out, skipped or could not start is reported as exactly that.
5. **Name no tool in the kernel.** Tools, languages and formats live in providers and in configuration.
6. **Portability rules apply now** ([decision 0009](decisions/0009-platform-order-and-portability-rules.md)): no shell scripts, no absolute paths, no platform-specific assumptions in anything committed.
7. **Do not weaken a check to make it pass.** A failing check is information about the design; record it and raise it.
8. **Nothing site-specific is committed:** no machine names, private paths, credentials or references to private infrastructure. Where a check runs is configured outside the repository.
