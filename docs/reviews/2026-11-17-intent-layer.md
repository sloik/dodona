# Review of the intent layer

Date: 2026-11-17. The layer added in draft 0.3 (intents, gates, the assurance scale, exceptions) was reviewed by one AI agent playing a lazy, not very capable agent whose only goal was to make dodona report `delivered` while doing as little work as possible. It also traced the model in `spec/intent/` by hand. One reviewer of the same lineage as the author is a weak form of review; more are wanted.

It found 14 routes or weaknesses. None was dismissed.

## Changed in response

| Route to an undeserved result | Change |
|---|---|
| Declare every gate soft or deferred up front: delivered with no check run | Gates are part of the baseline the owner confirms; an intent with no hard gate is `unguarded` and never delivered; policy sets a floor |
| Gates were not part of an intent's identity, so one could be edited silently | Identity covers statement, criteria, gates, limits, sample sizes, links to checks and children; any difference from the confirmed baseline is an amendment |
| The weakest link was always the owner's word, so the score said nothing | Judgement links and evidence links are reported separately; the score is the weakest evidence link |
| Nothing checks that a check tests its criterion | Stated as a judgement dodona cannot make; a named reviewer's word is recorded and marked if the reviewer did the work |
| The status word alone hid everything | A fixed headline on every result: gate mix, shown level, who agreed, exceptions, independence |
| Split a criterion into an all-soft child, or drop a child | Children are in the identity; totals are taken over descendants |
| A deferred gate due in the far future | Policy sets the longest limit; extending one is an amendment; open deferred gates are in the headline |
| A "varying" check with one run | Policy minimums; one run reads `sampled (1 of 1)`; declaring variance later is an amendment |
| Leave a link unreported to raise the score | Every evidence link is always evaluated; unreported is `none` |
| Owner confirms something it did not read, or the worker redrafts criteria | Confirmation names an exact identity and is voided by any change; that the owner read it stays in the trusted base, stated |
| Switch off the independent-approver rule in policy | A policy change is recorded and reported like an amendment |
| Hand-written statuses in the intents table | Labelled as worked out by hand and unverified |

## Not closed

- **A second identity as the "independent" approver.** This is the largest open hole. Nothing yet stops an agent from approving its own work under another name. Until identities are bound to something a working agent cannot create, every report says `independence: unverified`.
- **The model is narrower than its claims suggested.** `spec/CLAIMS.md` now says exactly what it does not cover. It needs a baseline, children, a policy floor and ordering of amendment before change. It was not altered while its first run is still queued.
- Claims C24, C26, C27 and C29 to C32 are not modelled.
- A less capable agent gets a complete headline and still no guidance on what to do next; that is the judge-only choice, to be revisited.
