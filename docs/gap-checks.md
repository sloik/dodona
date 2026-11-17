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

Three more checks run as their own tools in CI, because they need to build or install something:

| Tool | The gap behind it |
|---|---|
| `tools/check_examples.py` | The provider guide's examples were valid only because their author said so, and a schema change silently broke one |
| `tools/kit_adequacy.py` | A kit that no defective kernel fails proves nothing. Each planted defect must be rejected |
| `tools/path_differential.py` | Two implementations of the path check written from one document could disagree unnoticed |

The judge that decides whether a model run matched its expectation has its own tests in the same file, for the same reason: it once misread a correct result, and it must never turn an unfinished run into a pass.

Known gaps with no check yet are listed as open in the review logs under `docs/reviews/` and as unmodelled claims in `spec/CLAIMS.md`.
