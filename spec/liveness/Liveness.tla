------------------------------ MODULE Liveness ------------------------------
(***************************************************************************)
(* Every obligation eventually gets an answer (claim C22).                 *)
(*                                                                         *)
(* One obligation. A run of it can end three ways: with a verdict, with    *)
(* "unsupported", which is permanent and is a stated reason, not a         *)
(* verdict, or without finishing: an error, or a loss the kernel notices.  *)
(* A run happens only while the backend is up; an outage while a run is in *)
(* flight loses it.                                                        *)
(*                                                                         *)
(* THE ASSUMPTIONS. The property is true only under all of these, and each *)
(* is an assumption about the world or the kernel, not something shown:    *)
(*   1. The kernel keeps submitting whatever has no answer (fairness).     *)
(*   2. The backend comes back after an outage (fairness).                 *)
(*   3. A run in flight ends, one way or another (fairness).               *)
(*   4. Edits, outages, errors and losses each happen only a bounded       *)
(*      number of times. Without this nothing can be promised: a run that  *)
(*      is lost every time never finishes.                                 *)
(*   5. The kernel can tell that a run was lost. A run that hangs silently *)
(*      for ever is outside the model.                                     *)
(***************************************************************************)
EXTENDS Naturals

CONSTANTS MaxEdits, MaxOutages, MaxFailures, CanBeUnsupported, Mutant

VARIABLES st, backend, edits, outages, failures

vars == <<st, backend, edits, outages, failures>>

Mutants == {"none", "no_resubmit_after_unavailable", "no_resubmit_after_loss",
            "no_resubmit_after_error", "resubmits_unsupported"}
ASSUME Mutant \in Mutants /\ CanBeUnsupported \in BOOLEAN

Init == st = "unknown" /\ backend = "up" /\ edits = 0 /\ outages = 0 /\ failures = 0

Edit ==
    /\ edits < MaxEdits
    /\ edits' = edits + 1 /\ st' = "unknown"
    /\ UNCHANGED <<backend, outages, failures>>

\* The backend goes down. A run in flight is lost with it.
Down ==
    /\ backend = "up" /\ outages < MaxOutages
    /\ backend' = "down" /\ outages' = outages + 1
    /\ st' = IF st = "pending" THEN "lost" ELSE st
    /\ UNCHANGED <<edits, failures>>

Up == backend = "down" /\ backend' = "up" /\ UNCHANGED <<st, edits, outages, failures>>

Retryable ==
    {"unknown"}
    \cup (IF Mutant = "no_resubmit_after_unavailable" THEN {} ELSE {"unavailable"})
    \cup (IF Mutant = "no_resubmit_after_loss" THEN {} ELSE {"lost"})
    \cup (IF Mutant = "no_resubmit_after_error" THEN {} ELSE {"error"})
    \cup (IF Mutant = "resubmits_unsupported" THEN {"unsupported"} ELSE {})

Submit ==
    /\ st \in Retryable
    /\ st' = IF backend = "up" THEN "pending" ELSE "unavailable"
    /\ UNCHANGED <<backend, edits, outages, failures>>

\* A run ends with a verdict, or with "unsupported".
Complete ==
    /\ st = "pending" /\ backend = "up"
    /\ st' \in {"decided"} \cup (IF CanBeUnsupported THEN {"unsupported"} ELSE {})
    /\ UNCHANGED <<backend, edits, outages, failures>>

\* A run ends without finishing: an error, or a loss the kernel notices.
Fail ==
    /\ st = "pending" /\ failures < MaxFailures
    /\ st' \in {"error", "lost"}
    /\ failures' = failures + 1
    /\ UNCHANGED <<backend, edits, outages>>

Next == Edit \/ Down \/ Up \/ Submit \/ Complete \/ Fail

Spec == Init /\ [][Next]_vars /\ WF_vars(Submit) /\ WF_vars(Complete) /\ WF_vars(Up)
----------------------------------------------------------------------------
TypeOK ==
    /\ st \in {"unknown", "pending", "unavailable", "lost", "error", "decided", "unsupported"}
    /\ backend \in {"up", "down"}

\* Eventually the obligation has a verdict, or the stated reason that it
\* cannot be checked, and that does not change again.
EventuallyAnswered == <>[](st \in {"decided", "unsupported"})
=============================================================================
