# Working in this repository

dodona is built by agents, for agents. These rules bind anyone, human or model, who changes this repository.

1. **Read first:** [ARCHITECTURE.md](ARCHITECTURE.md), [MODEL.md](MODEL.md), then [decisions/README.md](decisions/README.md).
2. **A change of direction is a decision record.** Propose one by adding a record with status `proposed`. Only the project owner moves a record to `accepted`.
3. **Specification before implementation.** No kernel or provider code is added without the model property or conformance scenario that judges it, and a planted defect showing the check can fail.
4. **Only a pass is a pass.** Never describe anything as verified, checked or passing unless the check ran to completion and the run is recorded. Until a ledger exists, runs are recorded in [spec/CLAIMS.md](spec/CLAIMS.md). A check that is queued, timed out, skipped or could not start is reported as exactly that.
5. **Name no tool in the kernel.** Tools, languages and formats live in providers and in configuration.
6. **Portability rules apply now** ([decision 0009](decisions/0009-platform-order-and-portability-rules.md)): no shell scripts, no launchers for tools, no absolute paths, no platform-specific assumptions in anything committed.
7. **Do not weaken a check to make it pass.** A failing check is information about the design; record it and raise it.
8. **Do not grant yourself an exception.** If a check cannot be made to pass, say so and ask the owner of the intent. Whoever does the work never approves a change to what the work is judged against ([decision 0020](decisions/0020-exceptions-are-granted-by-the-intent-owner-and-recorded.md)).
9. **Nothing site-specific is committed outside `.github/`:** no machine names, private paths or credentials anywhere, and no reference to where checks run except in this repository's own site binding under `.github/` ([decision 0023](decisions/0023-stage-0-checks-run-in-ci-with-disposable-helpers.md)).
10. **Before pushing, run `python3 tools/check_repo.py`.** It must pass.
