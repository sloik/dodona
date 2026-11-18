# Second review of the kit: what was found and what was done

Date: 2026-11-18. Subject: the conformance kit as it stood after the newer scenarios were added.

A reviewer tried to break the kit. The reviewer wrote kernels with one defect each and ran the kit against them. A kit that accepts a defective kernel has a gap. The reviewer also compared the two real kernels on inputs the kit does not hold, and wrote hosts with one defect each.

## Tally

- 117 defective kernels were tried. The kit rejected 45 and accepted 72.
- 5 defective hosts were tried. The cases rejected none of them.
- The host itself recorded `passed` in five situations where it should have refused.

These numbers describe the kit before this change. The defective kernels have not been run again against the new material, so no new tally is claimed here.

## Findings and what was done

| Finding | What was done |
|---|---|
| A check value did not cover what was judged. A vouched refusal could be copied as an agreement. A vouched confirmation could be moved to another baseline. | New rule: no level above `helper` unless the check value also covers `kind`, `target`, `result` and `lineage`. The signer, the harness and the generator now always cover them. New scenario `acts/a_vouched_act_is_bound_to_what_it_judged`. |
| The kit accepted kernels that granted `apart` or more without full vouching. The kit only ever left out three of the seven fields. | New scenarios `acts/every_field_a_fact_reads_must_be_covered` and `acts/each_fact_at_its_edges`. |
| A kernel could sort `covers` before checking, or accept an uppercase or partly matching value. | New rule: `covers` is used as given and must already be sorted with no repeat. The value is lowercase and compared in full. New scenario `acts/the_check_value_is_exact`. |
| A policy key that is empty, not hexadecimal or of odd length was read differently by the two kernels. One accepted a value made with the empty key. | New rule: such a key names no key. Four scenarios `acts/a_key_that_is_not_a_key_vouches_for_nothing_*`. |
| Records that fail the act schema were graded differently by the two kernels. A sentence in the contract was false for a missing worker. | New rule: a malformed record is `self`. The contract lists exactly what malformed means. The false sentence is gone. New scenario `acts/a_record_that_fails_its_schema_is_self`, one step for each way. |
| The ledger judge never tested the length or the checksum. Fourteen defective readers were accepted. | The format is now stated exactly. New file `ledger/more-damage.json` with 24 whole files: 22 corrupt, one torn, one sound with an entry of another kind. The judge reads each one. For each corrupt one it requires a refused append that leaves the file alone. |
| The kernels disagreed on an entry of kind `note`, on an append with no kind, and on a null payload. | New rules: any non-empty kind is kept. An append with no string kind or no body is refused as `bad-request` and writes nothing. A payload that is not an entry is corrupt. The judge checks each. |
| Status scenarios used one shape. Many defective kernels passed. | Fifteen new status scenarios in all, counting those named in the rows below. They cover baseline order, two checks behind one criterion, which records count, floors above `helper`, pairings found by target, the project rule, uncovered before unguarded, soft criteria in the score, steps that name nothing. |
| The kernels disagreed on a match-check whose lineage names another intent. | The contract now says a match-check is found by its target alone. New scenario `status/a_match_check_is_found_by_its_target_alone`. |
| The kernels disagreed on a verdict of `error`, and one stopped on an empty body, on an act with no actor, and on names nothing defines. | New rules for each. New scenarios `status/what_is_not_a_record_counts_for_nothing` and `status/names_the_scenario_does_not_define`. |
| The kernels disagreed on a record whose preimage cannot be keyed. | New scenario `status/a_preimage_that_cannot_be_keyed_is_rejected`. The contract already said it. |
| The contract said two things about the order of a set in a core key. Only `closure` with three members was ever tested. A platform at the top level was read two ways. | One rule: UTF-16 code units, as the canonical encoding sorts keys. The schema sentence is corrected. New file `vectors/core-key-more.json` with 13 refusals and one acceptance. The key judge reads both files. |
| The host recorded `passed` for a tool the check was not given, for a tool named without a slash, for another tool digest, for another class of strength, and for runs without end. | Each is fixed in `tools/host.py`. A check may ask for 8 runs. Each fix has a case. |
| Five host rules had no case: the answer id, a NUL in an argument, a failure with no run, the ceiling for a failure, the opening echo. | A mode and a case for each. Each new case was seen to fail with its rule taken out, 12 trials in all. A session that fails to open no longer leaves the provider running. |
| A name in flight could be reused for another obligation, or recorded as unavailable. | New scenario `evidence/a_name_in_flight_is_taken_whatever_is_asked`. The contract now says names are shared by all obligations. |
| Reported by the kernel authors during this work: a record from another platform could raise the level shown. Two points about `shown` were guessed. A step naming nothing was untested outside status. | One more step in `status/the_headline_shows_the_weakest_link`. The contract now says what an intent with no criteria shows and how a stated `none` is taken. New scenarios `status/a_stated_none_is_none_and_no_criteria_show_nothing` and `a_step_that_names_nothing_changes_nothing` for intent, tree and plan. |

## How the expected values were made

Every expected value was worked out by hand from `conformance/README.md` as amended. Identities and check values come from the reference encoder and the reference signer. No kernel produced any of them. A second reading of the acts and status rules, written apart from the generator, agreed with all 45 acts and status scenarios. That is a cross-check by the same author, not an independent review.

Both kernels are expected to fail the new material until their authors bring them up to the amended contract.

## Still not covered

- The 72 accepted defects have not been run again. Nothing here shows how many the new material rejects.
- Ten defects stayed open in the reviewer's own check of the first closing scenarios. In acts: an actor that started itself; a make with a `-small` suffix; vouching for `cross-make` needing nothing more than `tested`. In status: the latest evidence record deciding; a `change` step replacing more than the preimage; the owner compared with the worker's id on confirmation; a failure reported where there is a conflict. In evidence: losing a finished run recording an error; a reused run name keeping the first run's inputs; a second `complete` with the same verdict being ignored. Nothing was added for these.
- A set whose order differs between UTF-8 bytes and UTF-16 code units cannot be shown with valid members. The rule is written and has no vector.
- The reason for refusing a preimage field other than `platform` is not decided.
- A `kind` that is the empty string, and an append whose `body` is null, are not tested. The words lean one way and nobody has decided.
- The act schema asks only for the worker's `id`. The new rule also asks for the worker's `session`. The schema was left as it is.
- Children that are intents of the same scenario, exceptions that change a gate, and time limits are still outside the status scenarios.
- The host rules are judged on the stage 0 host only. No kernel hosts a provider yet.
