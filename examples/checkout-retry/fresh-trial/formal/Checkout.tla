----------------------------- MODULE Checkout -----------------------------
EXTENDS Naturals

CONSTANT Mode
VARIABLES first, retry, timedOut, firstWasLateAfterRetry, charges, settled

Vars == <<first, retry, timedOut, firstWasLateAfterRetry, charges, settled>>

Init ==
    /\ first = "absent"
    /\ retry = "absent"
    /\ timedOut = FALSE
    /\ firstWasLateAfterRetry = FALSE
    /\ charges = 0
    /\ settled = FALSE

SubmitFirst ==
    /\ first = "absent"
    /\ first' = "submitted"
    /\ UNCHANGED <<retry, timedOut, firstWasLateAfterRetry, charges, settled>>

ProcessFirst ==
    /\ first = "submitted"
    /\ first' = "processed"
    /\ charges' = (IF Mode = "never-charge" THEN 0 ELSE 1)
    /\ UNCHANGED <<retry, timedOut, firstWasLateAfterRetry, settled>>

TimeoutFirst ==
    /\ first = "processed"
    /\ ~timedOut
    /\ timedOut' = TRUE
    /\ UNCHANGED <<first, retry, firstWasLateAfterRetry, charges, settled>>

SubmitRetry ==
    /\ timedOut
    /\ first = "processed"
    /\ retry = "absent"
    /\ retry' = "submitted"
    /\ UNCHANGED <<first, timedOut, firstWasLateAfterRetry, charges, settled>>

ProcessRetry ==
    /\ retry = "submitted"
    /\ retry' = "processed"
    /\ charges' = (IF Mode = "non-idempotent" THEN charges + 1 ELSE charges)
    /\ UNCHANGED <<first, timedOut, firstWasLateAfterRetry, settled>>

Settlement == settled \/ (charges > 0 /\ Mode # "never-settle")

ReceiveFirst ==
    /\ first = "processed"
    /\ first' = "replied"
    /\ firstWasLateAfterRetry' = (timedOut /\ retry \in {"processed", "replied"})
    /\ settled' = Settlement
    /\ UNCHANGED <<retry, timedOut, charges>>

ReceiveRetry ==
    /\ retry = "processed"
    /\ retry' = "replied"
    /\ settled' = Settlement
    /\ UNCHANGED <<first, timedOut, firstWasLateAfterRetry, charges>>

Next == SubmitFirst \/ ProcessFirst \/ TimeoutFirst \/ SubmitRetry
        \/ ProcessRetry \/ ReceiveFirst \/ ReceiveRetry

Spec == Init /\ [][Next]_Vars

AtMostOneCharge == charges <= 1
NoChargeReachable == charges = 0

BothRepliesAfterRetry == firstWasLateAfterRetry /\ retry = "replied"

PaidAfterRetryLateReply == BothRepliesAfterRetry /\ charges = 1 /\ settled
NoPaidAfterRetryLateReply == ~PaidAfterRetryLateReply

ChargedPendingAfterRetryLateReply == BothRepliesAfterRetry /\ charges = 1 /\ ~settled
NoChargedPendingAfterRetryLateReply == ~ChargedPendingAfterRetryLateReply
=============================================================================
