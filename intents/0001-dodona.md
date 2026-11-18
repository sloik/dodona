---
id: "0001"
title: An agent can find out whether what was defined was built and delivered, and how sure that is
owner: project owner
worker: the agents building dodona
parent: ""
touches:
  - everything
criteria: [{"id": "1", "words": "Each child intent is delivered", "gate": "hard", "checked_by": "Children 0002 to 0006"}, {"id": "2", "words": "dodona's own repository is judged by a dodona kernel, with every intent here reporting a derived status", "gate": "hard", "checked_by": "Not yet covered"}, {"id": "3", "words": "A less capable agent, given only dodona's output, correctly reports which criteria of a sample project are not shown", "gate": "deferred", "checked_by": "Not yet covered; needs a kernel and a trial"}, {"id": "4", "words": "A project outside this repository is judged with tools chosen by someone else", "gate": "deferred", "checked_by": "Not yet covered"}]
---

# 0001. An agent can find out whether what was defined was built and delivered, and how sure that is

An AI agent, possibly not a very capable one, is given work described in plain words. When it says the work is done, nobody should have to take its word for it. dodona is the thing that can be asked instead: it knows what was defined, what has been shown, how strongly, and what is still only claimed.

It must work with whatever decision format, checking tools and compilers a project chooses, on macOS, Linux and Windows, and it must be built using itself.

## Criteria

<!-- criteria: written by tools/intents.py from the front matter; do not edit -->
| # | Criterion | Gate | Checked by |
|---|---|---|---|
| 1 | Each child intent is delivered | hard | nothing a kernel reads yet. Children 0002 to 0006 |
| 2 | dodona's own repository is judged by a dodona kernel, with every intent here reporting a derived status | hard | nothing a kernel reads yet. Not yet covered |
| 3 | A less capable agent, given only dodona's output, correctly reports which criteria of a sample project are not shown | deferred | nothing a kernel reads yet. Not yet covered; needs a kernel and a trial |
| 4 | A project outside this repository is judged with tools chosen by someone else | deferred | nothing a kernel reads yet. Not yet covered |
<!-- end of criteria -->
