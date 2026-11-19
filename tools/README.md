# Tools

Stage-0 helpers ([decision 0023](../decisions/0023-stage-0-checks-run-in-ci-with-disposable-helpers.md)): small programs in Python's standard library, disposable, to be replaced by dodona itself. Each file's docstring shows how it is started, and `tools/check_docs.py` checks that what it shows matches the flags the program defines. [docs/doc-map.toml](../docs/doc-map.toml) says which documents describe each one.

| Tool | What it is for |
|---|---|
| [attest.py](attest.py) | Signs and verifies the keyed check value of an act record; the reference signer |
| [canonical.py](canonical.py) | Reference implementation of the [canonical encoding](../protocol/canonical-encoding.md) |
| [check_docs.py](check_docs.py) | Checks that the documents still describe the code, across the repository and for one change ([gap checks](../docs/gap-checks.md)) |
| [check_examples.py](check_examples.py) | Validates the schemas, the provider guide's examples and dodona's own policy with a JSON Schema validator |
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
| [path_differential.py](path_differential.py) | Compares a kernel's path check with the reference on random paths |
| [pathcheck.py](pathcheck.py) | Reference implementation of the [path check](../protocol/path-check.md) |
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
| [run_vectors.py](run_vectors.py) | Judges a kernel against the canonical-encoding vectors |
| [status.py](status.py) | Reports the status of this project from its ledger, worked out by a kernel |
| [tooltree.py](tooltree.py) | Reference for the [digest of a tool tree](../protocol/tool-tree-digest.md) |
