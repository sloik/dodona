---
id: "0001"
title: An agent can find out whether what was defined was built and delivered, and how sure that is
owner: project owner
parent: ""
touches:
  - everything
---

# 0001. An agent can find out whether what was defined was built and delivered, and how sure that is

An AI agent, possibly not a very capable one, is given work described in plain words. When it says the work is done, nobody should have to take its word for it. dodona is the thing that can be asked instead: it knows what was defined, what has been shown, how strongly, and what is still only claimed.

It must work with whatever decision format, checking tools and compilers a project chooses, on macOS, Linux and Windows, and it must be built using itself.

## Criteria

| # | Criterion | Gate | Checked by |
|---|---|---|---|
| 1 | Each child intent is delivered | hard | Children 0002 to 0006 |
| 2 | dodona's own repository is judged by a dodona kernel, with every intent here reporting a derived status | hard | Not yet covered |
| 3 | A less capable agent, given only dodona's output, correctly reports which criteria of a sample project are not shown | deferred | Not yet covered; needs a kernel and a trial |
| 4 | A project outside this repository is judged with tools chosen by someone else | deferred | Not yet covered |
