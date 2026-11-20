---
id: "0003"
title: Someone outside can write a provider from the documents alone
owner: project owner
worker: the agents building dodona
parent: "0001"
touches:
  - protocol/
criteria: [{"id": "1", "words": "Every message of every capability has a schema and a worked example", "gate": "hard", "checked_by": "Not yet covered"}, {"id": "2", "words": "The configuration, the lock and policy each have a reference", "gate": "hard", "checked_by": "Not yet covered"}, {"id": "3", "words": "An agent with no other context writes a working provider for a tool the authors did not choose", "gate": "deferred", "checked_by": "Not yet covered; needs a kernel", "condition": "an agent given only the documents in protocol/ and docs/ writes a provider for a tool the authors did not choose, and the provider passes the conformance kit", "limit_days": 90}]
---

# 0003. Someone outside can write a provider from the documents alone

A person or agent who has never spoken to the authors can plug in their own decision format, checker or compiler using only what is in the repository.

## Criteria

<!-- criteria: written by tools/intents.py from the front matter; do not edit -->
| # | Criterion | Gate | Checked by | Observed after delivery |
|---|---|---|---|---|
| 1 | Every message of every capability has a schema and a worked example | hard | nothing a kernel reads yet. Not yet covered |  |
| 2 | The configuration, the lock and policy each have a reference | hard | nothing a kernel reads yet. Not yet covered |  |
| 3 | An agent with no other context writes a working provider for a tool the authors did not choose | deferred | nothing a kernel reads yet. Not yet covered; needs a kernel | within 90 days of delivery: an agent given only the documents in protocol/ and docs/ writes a provider for a tool the authors did not choose, and the provider passes the conformance kit |
<!-- end of criteria -->
