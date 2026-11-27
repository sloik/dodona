---
id: "0001"
title: A paid checkout settles exactly once across a retry
owner: fixture-owner
worker: fixture-worker
criteria: [{"id": "1", "words": "The bounded checkout model preserves at-most-one debit and settlement after both replies", "gate": "hard", "checks": ["checkout/design"]}, {"id": "2", "words": "The simulated runtime debits at most once across the timeout and retry", "gate": "hard", "checks": ["tests/safety.test.js*"]}, {"id": "3", "words": "The simulated runtime settles a paid retry and ignores the late first reply", "gate": "hard", "checks": ["tests/settlement.test.js*"]}]
---

# 0001. A paid checkout settles exactly once across a retry

The two runtime criteria are assessed alongside the bounded design check.

<!-- criteria: written by tools/intents.py from the front matter; do not edit -->
| # | Criterion | Gate | Checked by | Observed after delivery |
|---|---|---|---|---|
| 1 | The bounded checkout model preserves at-most-one debit and settlement after both replies | hard | checks named `checkout/design` |  |
| 2 | The simulated runtime debits at most once across the timeout and retry | hard | checks named `tests/safety.test.js*` |  |
| 3 | The simulated runtime settles a paid retry and ignores the late first reply | hard | checks named `tests/settlement.test.js*` |  |
<!-- end of criteria -->
