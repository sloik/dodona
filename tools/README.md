# Tools

Stage-0 helpers ([decision 0023](../decisions/0023-stage-0-checks-run-in-ci-with-disposable-helpers.md)): small Python programs, disposable, to be replaced by dodona itself. All but two use only the standard library: `check_examples.py` and `check_transcript.py` need the `jsonschema` package. Each file's docstring shows how it is started, and `tools/check_docs.py` checks that what it shows matches the flags the program defines. [docs/doc-map.toml](../docs/doc-map.toml) says which documents describe each one.

| Tool | What it is for |
|---|---|
| [attest.py](attest.py) | Signs and verifies the keyed check value of an act record; the reference signer |
| [canonical.py](canonical.py) | Reference implementation of the [canonical encoding](../protocol/canonical-encoding.md) |
| [metrics.py](metrics.py) | Counts how complete and how well checked dodona is, from its own files, and fails a change that takes a ratcheted item away ([metrics](../docs/metrics.md)) |
| [check_docs.py](check_docs.py) | Checks that the documents still describe the code, across the repository and for one change ([gap checks](../docs/gap-checks.md)) |
| [check_examples.py](check_examples.py) | Validates the schemas, provider guide examples, policy, project intent criteria and draft lock fixtures. It also checks that each draft lock entry pins each platform at most once |
| [check_intents_provider.py](check_intents_provider.py) | Checks how the Markdown intents provider reports criteria and the obligations that check them |
| [check_models.py](check_models.py) | Judges every model-check case listed in `spec/*/expected.json` |
| [check_repo.py](check_repo.py) | The repository checks that need no model checker; must pass before a push ([gap checks](../docs/gap-checks.md)) |
| [check_states.py](check_states.py) | Requires a kernel to give the model's own answer on every state a model reached |
| [check_transcript.py](check_transcript.py) | Validates every message of a recorded provider session against the protocol schemas |
| [confirm.py](confirm.py) | The owner confirms an intent's criteria and gates, at a terminal, into `records/owner.ledger` |
| [gen_kit_vectors.py](gen_kit_vectors.py) | Writes the kit files whose expected values need hashing or keyed check values, and checks them |
| [gen_unicode_tables.py](gen_unicode_tables.py) | Writes the first kernel's Unicode tables from the official data files |
| [gen_wrong_types.py](gen_wrong_types.py) | Writes the kit scenarios whose steps carry values of the wrong type, and checks them |
| [harness.py](harness.py) | A reference harness: starts a checker itself and signs what it did |
| [host.py](host.py) | Runs this project's checks through a provider, an executor and a kernel, in three steps |
| [intents.py](intents.py) | Reads the intent files one way only, and writes each one's criteria table |
| [keep.py](keep.py) | Moves what one model run keeps for the next, and reports about reuse |
| [kernel_differential.py](kernel_differential.py) | Compares two kernels on inputs the conformance kit does not contain |
| [kit_adequacy.py](kit_adequacy.py) | Plants each listed defect in the first kernel and requires the kit to reject it |
| [ledger.py](ledger.py) | Reads and writes the reference ledger format |
| [path_differential.py](path_differential.py) | Compares a kernel's path check with the reference on random paths |
| [pathcheck.py](pathcheck.py) | Reference implementation of the [path check](../protocol/path-check.md) |
| [policy_input.py](policy_input.py) | Validates a policy and prepares the fields and defaults a kernel uses |
| [project_run.py](project_run.py) | Reference command for running a project's checks and recording verdicts |
| [project_status.py](project_status.py) | Reference command for reporting a project's status from providers, ledgers and policy |
| [provider_host.py](provider_host.py) | A small reference host for one provider session |
| [run_attest_check.py](run_attest_check.py) | Has a kernel grade check values the reference signer makes at test time |
| [run_check_cases.py](run_check_cases.py) | Judges `tools/host.py` against a checker that breaks one rule at a time |
| [run_harness_check.py](run_harness_check.py) | Judges the reference harness and a kernel together |
| [run_input_cases.py](run_input_cases.py) | Judges how strictly a kernel reads its input |
| [run_key_vectors.py](run_key_vectors.py) | Judges a kernel against the core-key vectors |
| [run_kit.py](run_kit.py) | Judges a kernel against the conformance kit's scenarios |
| [run_ledger_cases.py](run_ledger_cases.py) | Judges a kernel's ledger, with damage at every byte and two writers at once |
| [run_path_vectors.py](run_path_vectors.py) | Judges a kernel against the path-check vectors |
| [run_provider_cases.py](run_provider_cases.py) | Judges a host against the misbehaving provider |
| [run_run_cases.py](run_run_cases.py) | Judges a project's run against scripted providers and a batch executor |
| [run_status_cases.py](run_status_cases.py) | Judges a project's status against scripted providers and the reference report |
| [run_vectors.py](run_vectors.py) | Judges a kernel against the canonical-encoding vectors |
| [status.py](status.py) | Reports the status of this project from its ledger, worked out by a kernel |
| [tooltree.py](tooltree.py) | Reference for the [digest of a tool tree](../protocol/tool-tree-digest.md) |

## Qualifying an isolated harness

A qualification record for the deployment in [issue 26](https://github.com/sloik/dodona/issues/26) needs evidence from the party that operates the harness and the verifier.

- **Control of the key and policy.** Identify the harness that makes the shared-key check value and the kernel that verifies it. Record who controls each and the evidence that neither the working agent nor the checker can reach the key or control either key holder. Record the protected policy revision the verifier actually used, including its allowed key names and separation floors. A working-copy fallback leaves the policy anchor unestablished. [Decision 0027](../decisions/0027-vouching-is-a-keyed-check-value-and-nothing-vouches-yet.md)
- **Provenance of the act.** Keep the ticket, exact target, kind, result and lineage with the attested record. Record who chose and started the checker, issued its brief and supplied its known-wrong and known-right cases. Keep the role and content hash of each item the checker received, the fresh-session evidence and the outcomes of all attempts. The sources for those facts must be independent of the worker. [Decision 0024](../decisions/0024-separation-is-graded-not-enforced.md)
- **Transcript.** Retain the checker output bytes in the qualification record or in an artifact it identifies. Check that their digest equals the transcript digest in the attested act. The reference harness collects the output during the run and returns its digest in the act record. [Reference harness](harness.py)

The reference harness starts a new process with named inputs and a small environment. It runs under the same system user, reads the key from a file and accepts several provenance facts from its caller. The public fixture run at `5a53a8b` completed eight harness cases per kernel on Linux, macOS and Windows, including the control that required the real checker to accept the known-right case and refuse the known-wrong case, and confirmed the always-accepting checker failed the control. Those results cover fixture grading. Deployment isolation and independently sourced provenance remain open. [Reference harness](harness.py) · [Hosted fixture run](https://github.com/sloik/dodona/actions/runs/44913578774)
