# Checkout retry evidence pilot

This simulated checkout has two requests for the same order. The fake service can debit before either response reaches the client. The first request can time out. The client retries, receives the retry result and subsequently receives the late first result. The fixture uses no real payment service.

The formal model bounds the workload to one order, at most two attempts, two deliverable responses, and zero through two debits. It allows either response to arrive or remain pending. The reachability example assumes that the retry and delayed first result can both be delivered. It has no deadline or fairness assumption for real progress.

| Case | Expected evidence |
|---|---|
| Baseline design | At most one debit and a settled status after requests with a positive debit have both replied |
| Reach paid | A trace reaches a debit and settled order after the timeout, retry and both replies |
| Remove idempotency | Two debits refute the safety property |
| Disable charging | At-most-one holds and no paid-settled state is reachable in the bounded model |
| Disable settlement | At-most-one holds and a trace reaches a debit with both replies delivered while the order stays pending |

Runtime tests exercise the timeout, retry and late original response on a fake service. A separate test requires the client to settle. Code and model are bound separately and can retain evidence independently. Changing only the settlement line should invalidate the runtime inputs while retaining the unchanged model evidence.

The Node and model result records are produced through Dodona. The model searches use the configured model executor. The model’s bounds, assumptions and exact archived artifacts belong in the recorded readout.

## Recorded observations

The short model searches below use the corrected model in the fixture at `81fd630`. TLC 1.7.4 checked the stated bounds through the shared queue. The design exhausted its queue after nine distinct states at depth six.

| Model case | Completed result |
|---|---|
| Design | At most one debit. With a debit and both replies delivered after a retry, the order was settled in every reachable state. Native exit 0. |
| Reach paid | The reachability control produced a trace with two attempts, both replies, one debit and a settled order. Native exit 12 names `NeverSettledAfterRetry`. |
| Remove idempotency | The second request produced a second debit while the order remained pending. Native exit 12 names `AtMostOneDebit`. |
| Disable charging | The full search found no safety violation and no reachable paid settlement. Native exit 0. |
| Disable settlement | Safety held. A second run produced one debit and both replies with a pending order. Native exits 0 and 12, respectively. |

The captured counterexample for the retry without idempotency is `Init → FirstRequest → Timeout → Retry`. Its last state has attempts 2, debits 2 and no delivered replies. The model expresses what is reachable under its bounds. The retry evidence supplies neither a real service's delivery guarantees nor a time limit.

The runtime fixture delivered the retry reply and then the late original reply. Its safety test passed with one debit in the baseline, with zero when charging was disabled, and with one when settlement was disabled. The separate settlement test passed in the baseline and failed in the zero-debit and charged-but-pending runs. Removing idempotency failed the safety test with two debits.

### Native evidence and implementation drift

The native test uses a declared fixture owner and worker with distinct fixture session labels. The demonstration itself has separation `self`. Both kernel readers agreed at each stage.

| Stage | Current model evidence | Code evidence | Native project and intent |
|---|---|---|---|
| Baseline | Six current results, including the expected counterexamples | Both sampled runtime obligations passed | `passed` and `fulfilled` |
| Change only `SETTLE_PAID_RETRY` to false | All six still current | Both code obligations became unknown | `unknown` and `open` |
| Run the same Node checks again | All six reused from the same ledger keys | Safety passed. Settlement failed. | `failed` and `open` |

The six model keys stayed identical across the implementation change and rerun. The recorded verdict for a model mutation means that the expected violation matched its declared property. The runtime obligations report sampled results. The approval acts use fixture identifiers purely to exercise the documented policy floor. [Model outcomes and traces](evidence/model-results.json) · [Runtime outcomes](evidence/runtime-results.json) · [Native status receipt](evidence/native-status-receipt.json).

## Try the example

Use a separate checkout containing the files in this directory. The two runtime tests run with Node 24.22.3 and require no packages or network. Run them from the example root.

```text
node --test --test-reporter=tap -- tests/safety.test.js
node --test --test-reporter=tap -- tests/settlement.test.js
```

Set `SETTLE_PAID_RETRY` to `false` in the example copy and run the same commands. The safety test still observes one debit. The settlement test fails because the order stays pending. The model files and their inputs have the same content as before.

For a Dodona run, the example's `dodona.toml` binds the model cases, the runtime tests and the Markdown intent separately. Configure an executor with the matching tool and platform capabilities. Use `fixture-policy.json` as the policy in the status and run requests. The recorded example uses a fixture confirmation and a fresh run ledger. The commands report evidence as unknown until the appropriate executor has returned a current verdict, and they show the actual status of each obligation. [Project request contract](../../conformance/README.md#how-a-projects-status-is-judged) · [Provider bindings](../../providers/README.md).

## Pinned replay

The runtime comparator replayed a timeout, the retry reply and the late original reply against the original checkout source and a candidate with settlement disabled. It compared attempts, reply order, observed debits and checkout state.

| Fake reply content | Original | Candidate | Agreement |
|---|---|---|---|
| Both replies acknowledge the debit | One debit, settled | One debit, pending | No |
| Both replies omit the paid acknowledgement | One debit, pending | One debit, pending | Yes |

The second replay leaves the expected paid settlement open for both versions. The model assumes replies describe the debit faithfully. The replay tests a runtime case outside that assumption. The receipt records the two commits, source hashes, input hash and all observations. [Replay receipt](evidence/replay-results.json).

## Fresh public-docs pilot

A fresh agent used the released providers and public documentation to build a separate checkout fixture. The review grade is `helper`. The trial used the released kernel at `fa51d47` and measured Node 26.10.0 on macOS ARM64. Its model covers one fake order, one retry and one possible reply per attempt. The settled path assumes successful payment processing, both replies arriving and settlement enabled. It establishes reachability within those bounds. [Released provider](https://github.com/sloik/dodona/tree/fa51d4730718b8aac41c54e97d1e6dbb7f93e839/providers) · [Fresh trial receipt](evidence/fresh-public-docs-pilot.json).

All eight shared-queue model cases completed. The baseline search exhausted the queue after 14 distinct states and found the safety property held. A separate reachability search found one charge and a settled order after both replies. Removing idempotency produced a six-state counterexample ending in the retry's second charge. The zero-charge and disabled-settlement variants both satisfied the safety property and failed the settled-path check. Another witness reached one charge and both replies with an order still pending.

The two seed readers agreed on all six reports. The Node obligations used both the checkout source and the reply schedule.

| Code stage | Safety | Settlement | macOS project |
|---|---|---|---|
| Baseline | Passed | Passed | Unknown |
| Settlement default changed | Unknown | Unknown | Unknown |
| Runtime checks rerun | Passed | Failed | Failed |

The intent was draft throughout the fresh trial. Changing the settlement default changed both Node keys. Both readers reported `never-run` for the new keys and the old ledger entries were still available. The model-only run reused all eight results and started zero new checks. After rerunning the Node checks, settlement was the weakest criterion. [Fresh trial receipt](evidence/fresh-public-docs-pilot.json).

The fresh replay compared the same seven events at two pinned commits. Under normal defaults the original settled and the candidate stayed pending, with one charge in each. With settlement disabled in both versions the full traces agreed with one charge and a pending order.

The trial found a missing runnable external-project `run` and `status` example. Its documented wire schema also needs a clear boundary with the live stage-0 report and ledger. The run kept the exact output and key references needed to audit the staleness result. The released project command reports `conformance.check` as unserved. The Node verdict in this example records sampled implementation behavior. [Provider guide](../../docs/writing-a-provider.md) · [Project request contract](../../conformance/README.md#how-a-projects-status-is-judged).
