# Designing the separation scale

Date: 2026-11-17. The open hole after the intent-layer review was that an agent could act as its own "independent" approver. The project owner's direction: agents should be able to use sub-agents as verifiers, dodona cannot enforce their independence, so grade it and give partial credit.

Three AI agents each wrote a proposal without seeing the others', from three viewpoints: audit and safety assurance; building multi-agent systems in production; and a weak agent that reads only the first line, paired with a plain-language designer. [Decision 0024](../../decisions/0024-separation-is-graded-not-enforced.md) is the combination.

| Taken from | What |
|---|---|
| Audit and assurance | The name *separation*, since "independence" promises more than can be shown. Grading per act, not per agent. Verdict shopping as the standard attack. A separate axis with one narrow cap, and counts instead of a blended number. Not grading checks that anyone can rerun |
| Multi-agent systems | A source for every fact: checked, attested or declared. Tickets before each attempt. A known-bad case as the only thing that measures whether a checker can say no. The record format. The list of what stays unexposed |
| Weak agent and plain language | The default must be the lowest level, or silence is rewarded. Three yes-or-no questions. Which acts block, cap or are only shown. Level names that cannot be confused with the evidence scale. The headline and the default policy |

Where the proposals disagreed:

- **A level for "a person did it".** Two proposals had one. It is left out: without credentials dodona cannot tell a person from an agent, and with them the top level already covers it.
- **Whether a different model family ranks above or below a tested checker.** A checker that has been shown able to reject a bad case ranks first; a different make is added on top. A different make that was never tested proves little.
- **How many levels.** Five to seven were proposed. Six were kept, one of which cannot be granted yet.

Not yet done: the three proposals were combined by the same author that wrote the rest of the design, and the result has not itself been reviewed.
