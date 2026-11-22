---
id: "0001"
title: An agent can find out whether what was defined was built and delivered, and how sure that is
owner: project owner
worker: the agents building dodona
parent: ""
touches:
  - everything
criteria: [{"id": "1", "words": "Each child intent is delivered", "gate": "hard", "checked_by": "Children 0002 to 0006"}, {"id": "2", "words": "dodona's own repository is judged by a dodona kernel, with every intent here reporting a derived status", "gate": "hard", "checked_by": "Hosted Linux replay 44925244772 produced the same retained ledger status report in native Rust and the pinned JavaScript judge. All six intents were draft at shown level none. See intents/README.md for the replay and historical main result."}, {"id": "3", "words": "A less capable agent, given only dodona's output, correctly reports which criteria of a sample project are not shown", "gate": "deferred", "checked_by": "Not yet covered; needs a kernel and a trial", "condition": "a sample project with criteria not shown is given to a less capable agent with only dodona's output, and it names exactly those criteria", "limit_days": 90}, {"id": "4", "words": "A project outside this repository is judged with tools chosen by someone else", "gate": "deferred", "checked_by": "Not yet covered", "condition": "someone other than dodona's authors runs dodona on a project of theirs with tools they chose, and its report agrees with what their own checks show", "limit_days": 90}]
---

# 0001. An agent can find out whether what was defined was built and delivered, and how sure that is

An AI agent, possibly not a very capable one, is given work described in plain words. When it says the work is done, nobody should have to take its word for it. dodona is the thing that can be asked instead: it knows what was defined, what has been shown, how strongly, and what is still only claimed.

It must work with whatever decision format, checking tools and compilers a project chooses, on macOS, Linux and Windows, and it must be built using itself.

## Criteria

<!-- criteria: written by tools/intents.py from the front matter; do not edit -->
| # | Criterion | Gate | Checked by | Observed after delivery |
|---|---|---|---|---|
| 1 | Each child intent is delivered | hard | nothing a kernel reads yet. Children 0002 to 0006 |  |
| 2 | dodona's own repository is judged by a dodona kernel, with every intent here reporting a derived status | hard | nothing a kernel reads yet. Hosted Linux replay 44925244772 produced the same retained ledger status report in native Rust and the pinned JavaScript judge. All six intents were draft at shown level none. See intents/README.md for the replay and historical main result. |  |
| 3 | A less capable agent, given only dodona's output, correctly reports which criteria of a sample project are not shown | deferred | nothing a kernel reads yet. Not yet covered; needs a kernel and a trial | within 90 days of delivery: a sample project with criteria not shown is given to a less capable agent with only dodona's output, and it names exactly those criteria |
| 4 | A project outside this repository is judged with tools chosen by someone else | deferred | nothing a kernel reads yet. Not yet covered | within 90 days of delivery: someone other than dodona's authors runs dodona on a project of theirs with tools they chose, and its report agrees with what their own checks show |
<!-- end of criteria -->
