# Records kept in the repository

`owner.ledger` holds the acts of owners: confirmations that an intent's criteria and gates are what was meant. It is written only by `tools/confirm.py`, run by the owner at a terminal, and committed like any other change, so every entry can be seen before it reaches the protected branch ([decision 0028](../decisions/0028-a-confirmation-is-the-owners-word-graded-like-any-act.md)).

The file does not exist until the first confirmation. Results of checks are not kept here: they come from runs.
