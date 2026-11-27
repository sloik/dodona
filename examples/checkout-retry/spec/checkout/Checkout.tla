----------------------------- MODULE Checkout -----------------------------
EXTENDS Naturals

CONSTANTS Deduplicate, AllowDebit, AllowSettlement
VARIABLES attempts, timedOut, delivered, debits, settled

vars == <<attempts, timedOut, delivered, debits, settled>>

Init ==
    /\ attempts = 0
    /\ timedOut = FALSE
    /\ delivered = {}
    /\ debits = 0
    /\ settled = FALSE

FirstRequest ==
    /\ attempts = 0
    /\ attempts' = 1
    /\ debits' = IF AllowDebit THEN 1 ELSE 0
    /\ UNCHANGED <<timedOut, delivered, settled>>

Timeout ==
    /\ attempts = 1
    /\ ~settled
    /\ ~timedOut
    /\ 1 \notin delivered
    /\ timedOut' = TRUE
    /\ UNCHANGED <<attempts, delivered, debits, settled>>

Retry ==
    /\ attempts = 1
    /\ timedOut
    /\ ~settled
    /\ attempts' = 2
    /\ debits' = IF AllowDebit /\ (~Deduplicate \/ debits = 0) THEN debits + 1 ELSE debits
    /\ UNCHANGED <<timedOut, delivered, settled>>

Deliver(attempt) ==
    /\ attempt \in 1..attempts
    /\ attempt \notin delivered
    /\ delivered' = delivered \cup {attempt}
    /\ settled' = (settled \/ (AllowSettlement /\ debits > 0 /\ (attempt = 2 \/ ~timedOut)))
    /\ UNCHANGED <<attempts, timedOut, debits>>

Next == FirstRequest \/ Timeout \/ Retry \/ \E attempt \in 1..2: Deliver(attempt)

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ attempts \in 0..2
    /\ timedOut \in BOOLEAN
    /\ delivered \subseteq 1..attempts
    /\ debits \in 0..2
    /\ settled \in BOOLEAN

AtMostOneDebit == debits <= 1

BothRepliesAfterRetry == attempts = 2 /\ timedOut /\ delivered = {1, 2}
SettledAfterRetry == BothRepliesAfterRetry /\ debits > 0 /\ settled
ChargedPendingAfterRetry == BothRepliesAfterRetry /\ debits > 0 /\ ~settled

\* These two deliberately named negatives ask whether the states are reachable.
NeverSettledAfterRetry == ~SettledAfterRetry
NeverChargedPending == ~ChargedPendingAfterRetry

=============================================================================
