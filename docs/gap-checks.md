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
| `gap_every_check_is_listed` | A check whose reason is lost gets deleted by mistake |

The judge that decides whether a model run matched its expectation has its own tests in the same file, for the same reason: it once misread a correct result, and it must never turn an unfinished run into a pass.

Known gaps with no check yet are listed as open in the review logs under `docs/reviews/` and as unmodelled claims in `spec/CLAIMS.md`.
