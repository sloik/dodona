# Gap checks

The rule: **a gap that is found becomes a check.** When a review, a mistake or a run shows that something could be wrong without anyone noticing, a check is added to `tools/check_repo.py` so the same gap cannot open again unseen. A check is added with the gap that caused it, and is first seen to fail.

These checks need no model checker. They run on every pull request on macOS, Linux and Windows, and on the project's own runner on every change to `main`.

| Check | The gap behind it |
|---|---|
| `check_claims_match_runs` | A model was rewritten and three claims still read "checked" from a run of the old version. A claim may be marked checked only while a recorded run matches the model files as they are now |
| `gap_readme_counts` | The README's count of checked claims and of decisions went stale after the documents changed |
| `gap_claims_name_real_properties` | An intent pointed at claims and a results file that did not cover what it said. Every property a claim names must exist in the model |
| `gap_every_property_has_a_defect` | A property was listed as checked although nothing had shown it could fail. Every property checked in a design case needs a case in which it is violated |
| `gap_decisions_are_well_formed` | Records were marked accepted before the owner had read them, and a decision without a way to be shown wrong is an opinion |
| `gap_vocabulary_is_the_same_everywhere` | Capability names and level names differed between the schemas and the documents |
| `gap_nothing_private_or_unportable` | The repository is public and must behave the same on three platforms: no private paths, no shell scripts |
| `gap_workflows_are_safe` | A project runner must never execute code from a pull request, and an unpinned action can change under us |
| `gap_path_check_matches_its_vectors` | The path rules were prose only, and reviewers showed names that would be accepted on one platform and refused on another. The reference implementation must agree with every hand-written vector |
| `gap_repository_paths_are_portable` | dodona's own files must pass dodona's own path rules |
| `gap_canonical_vectors_are_consistent` | A test vector whose hash is not the hash of its own text would mislead every implementer |
| `gap_every_modelled_case_has_a_scenario` | A defect planted in a formal model protects a kernel only if a scenario carries it into the kit. Every modelled case needs a scenario or a stated reason |
| `gap_kit_judge_is_strict` | The judge of model runs once misread a result. The kit's judge must refuse an empty, short or wrong answer |
| `gap_own_policy_fits_the_schema` | dodona's own policy file was first written with field names the policy schema did not have |
| `gap_no_generated_files_are_tracked` | Compiled caches were committed by mistake, and build output contains private paths |
| `gap_provider_cases_match_the_provider` | A misbehaviour case that names a mode the provider does not have would quietly test the well-behaved path and pass |
| `gap_every_check_is_listed` | A check whose reason is lost gets deleted by mistake |
| `gap_kit_shown_claims_are_exercised` | Claims shown by the kit and not by a model had no status of their own, and nothing tied them to a tool that runs. Each must name tools that exist and that CI runs, and may never be marked checked |
| `gap_kit_judge_hides_the_answers` | The kit judge sent each scenario to the kernel with the expected results in it. A program that printed them back passed every scenario |
| `gap_generated_kit_files_are_current` | Kit files that hold hashes and keyed check values are generated. Edited by hand, or left behind by a change to the generator, they would be wrong unseen |
| `gap_driver_refuses_outside_the_queue` | The one file that starts the model checker could be run by hand anywhere. It must refuse, even when given a made-up job marker |
| `gap_one_reader_of_checker_output` | The provider and the older model tool each read the checker's output their own way and could have disagreed about what a violation is |
| `gap_an_unfinished_job_proves_nothing` | Six claims were marked checked from a job the queue had stopped part of the way, and a tool nobody had measured was indistinguishable from one not yet pinned. A job with no end marker, or a tool with no measurement, may never yield a verdict. A second review showed the queue can mark a job failed after its files are written, and that an older way of sending jobs had none of these checks: every job now goes through one gate that needs the queue's clean exit and the marker both |
| `gap_tool_tree_digest_matches_its_vectors` | How the digest of a tool tree is computed was not written down, so nobody else could have checked a lock. The rule now has vectors, and the reference must agree with them |
| `gap_every_tool_compiles` | A syntax error in the status command reached the working branch, because no check ever ran that file |
| `gap_an_intent_reads_one_way_only` | Intent rows that a person sees but the reader skipped, or gates it misread, let an intent be reported fulfilled with a hard criterion never checked; and results written by hand into the owner's ledger counted as passed. Criteria are now data in the front matter, the table is written from it, and anything else that looks like criteria is refused |
| `gap_runner_versions_agree` | An automatic update moved one CI job to a new Ubuntu version and left the others, so steps that run only on the named old version would have skipped without a word. All workflows use one Ubuntu version, and a step limited to a named system must name one that exists. An update that misses a line now fails on its own pull request |

More checks run as their own tools in CI, because they need to build or install something:

| Tool | The gap behind it |
|---|---|
| `tools/check_examples.py` | The provider guide's examples were valid only because their author said so, and a schema change silently broke one |
| `tools/kit_adequacy.py` | A kit that no defective kernel fails proves nothing. Each planted defect must be rejected |
| `tools/path_differential.py` | Two implementations of the path check written from one document could disagree unnoticed |
| `tools/run_check_cases.py` | The rules a schema cannot express were prose. A checker that breaks each one in turn must be refused by the host, and nothing recorded as passed |
| `tools/check_transcript.py` | The first real provider sent three kinds of message its own schemas refused, and nothing noticed until a recorded session was validated |
| `tools/run_ledger_cases.py` | A ledger entry cut short by a crash, or two writers at once, could lose or corrupt a record silently |
| `tools/run_ledger_cases.py`, again | The ledger judge changed bytes only where the chain of entries would notice, so a reader that compared neither the length nor the checksum passed. Twenty-four whole files now break one thing each |
| `tools/gen_wrong_types.py` | Two kernels disagreed on steps whose values had the wrong type, and the comparison tool never tried such values. Six scenarios repeat each step with one value of the wrong type, which must change nothing |
| `tools/run_input_cases.py` | One kernel read a repeated key or a number written as `1.0` without complaint, so a record could be signed with one value and read with another |
| `tools/run_harness_check.py` | Separation above helper rested on a signer that signed whatever it was handed. The reference harness must really start a checker, a kernel must grade its record above helper, and a checker that agrees with everything must be seen through |
| `tools/run_attest_check.py` | Check values in the kit were made once by the kit's author. A kernel must also accept ones made now and refuse them once the record is changed |
| `tools/kernel_differential.py` | Two kernels can both pass the kit and still differ where the kit does not look. On its first run it found a step order the contract said nothing about, on which one kernel crashed |

The judge that decides whether a model run matched its expectation has its own tests in the same file, for the same reason: it once misread a correct result, and it must never turn an unfinished run into a pass.

Known gaps with no check yet are listed as open in the review logs under `docs/reviews/` and as unmodelled claims in `spec/CLAIMS.md`.
