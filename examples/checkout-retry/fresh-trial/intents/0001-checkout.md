---
id: "0001"
title: Fake checkout charges at most once and settles on the retry and late-reply path
owner: checkout intent owner
worker: pilot helper
criteria: [{"id": "1", "words": "At most one fake capture through timeout retry and late reply", "gate": "hard", "checks": ["checkout/safety.test.js*"]}, {"id": "2", "words": "A successful fake capture leaves the checkout settled", "gate": "hard", "checks": ["checkout/progress.test.js*"]}]
---

# 0001. Fake checkout charges at most once and settles on the retry and late-reply path

The expected trace uses one synthetic order and the fake payment gateway.

## Criteria

<!-- criteria: written by tools/intents.py from the front matter; do not edit -->
| # | Criterion | Gate | Checked by | Observed after delivery |
|---|---|---|---|---|
| 1 | At most one fake capture through timeout retry and late reply | hard | checks named `checkout/safety.test.js*` |  |
| 2 | A successful fake capture leaves the checkout settled | hard | checks named `checkout/progress.test.js*` |  |
<!-- end of criteria -->
