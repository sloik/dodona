------------------------------ MODULE Liveness ------------------------------
(***************************************************************************)
(* Every obligation eventually gets an answer (claim C22).                 *)
(*                                                                         *)
(* One obligation. A run of it can end three ways: with a verdict, with    *)
(* "unsupported", which is permanent and is a stated reason, not a         *)
(* verdict, or without finishing: an error, or a loss the kernel notices.  *)
(* A run happens only while the backend is up; an outage while a run is in *)
(* flight loses it. Whether the obligation can be checked at all is fixed   *)
(* from the start; "unsupported" is the right answer only when it cannot.   *)
(*                                                                         *)
(* Two directions. EventuallyAnswered says an answer comes; it cannot tell *)
(* a right answer from a kernel that gives up early by calling a           *)
(* retryable failure "unsupported". AnswerIsRight checks that direction.   *)
(*                                                                         *)
(* THE ASSUMPTIONS. The property is true only under all of these, and each *)
(* is an assumption about the world or the kernel, not something shown:    *)
(*   1. The kernel keeps submitting whatever has no answer (fairness).     *)
(*   2. The backend comes back after an outage (fairness).                 *)
(*   3. A run in flight ends, and once the allowed number of errors and    *)
(*      losses is used up, every run that is started completes with its    *)
(*      answer (fairness). That is stronger than "it ends somehow".         *)
(*   4. Edits, outages, errors and losses each happen only a bounded       *)
(*      number of times. Without this nothing can be promised: a run that  *)
(*      is lost every time never finishes.                                 *)
(*   5. The kernel can tell that a run was lost. A run that hangs silently *)
(*      for ever is outside the model.                                     *)
(***************************************************************************)
EXTENDS Naturals

CONSTANTS MaxEdits, MaxOutages, MaxFailures, CanBeUnsupported, Mutant

VARIABLES st, backend, edits, outages, failures, checkable

vars == <<st, backend, edits, outages, failures, checkable>>

Mutants == {"none", "no_resubmit_after_unavailable", "no_resubmit_after_loss",
            "no_resubmit_after_error", "resubmits_unsupported", "gives_up_on_error"}
ASSUME Mutant \in Mutants /\ CanBeUnsupported \in BOOLEAN

Init == st = "unknown" /\ backend = "up" /\ edits = 0 /\ outages = 0 /\ failures = 0
        /\ checkable \in (IF CanBeUnsupported THEN BOOLEAN ELSE {TRUE})

Edit ==
    /\ edits < MaxEdits
    /\ edits' = edits + 1 /\ st' = "unknown"
    /\ UNCHANGED <<backend, outages, failures, checkable>>

\* The backend goes down. A run in flight is lost with it.
Down ==
    /\ backend = "up" /\ outages < MaxOutages
    /\ backend' = "down" /\ outages' = outages + 1
    /\ st' = IF st = "pending" THEN "lost" ELSE st
    /\ UNCHANGED <<edits, failures, checkable>>

Up == backend = "down" /\ backend' = "up" /\ UNCHANGED <<st, edits, outages, failures, checkable>>

Retryable ==
    {"unknown"}
    \cup (IF Mutant = "no_resubmit_after_unavailable" THEN {} ELSE {"unavailable"})
    \cup (IF Mutant = "no_resubmit_after_loss" THEN {} ELSE {"lost"})
    \cup (IF Mutant = "no_resubmit_after_error" THEN {} ELSE {"error"})
    \cup (IF Mutant = "resubmits_unsupported" THEN {"unsupported"} ELSE {})

Submit ==
    /\ st \in Retryable
    /\ st' = IF backend = "up" THEN "pending" ELSE "unavailable"
    /\ UNCHANGED <<backend, edits, outages, failures, checkable>>

\* A run ends with a verdict, or with "unsupported" when the obligation cannot be checked.
Complete ==
    /\ st = "pending" /\ backend = "up"
    /\ st' = IF checkable THEN "decided" ELSE "unsupported"
    /\ UNCHANGED <<backend, edits, outages, failures, checkable>>

\* A run ends without finishing: an error, or a loss the kernel notices.
Fail ==
    /\ st = "pending" /\ failures < MaxFailures
    /\ st' \in {"error", "lost"} \cup (IF Mutant = "gives_up_on_error" THEN {"unsupported"} ELSE {})
    /\ failures' = failures + 1
    /\ UNCHANGED <<backend, edits, outages, checkable>>

Next == Edit \/ Down \/ Up \/ Submit \/ Complete \/ Fail

Spec == Init /\ [][Next]_vars /\ WF_vars(Submit) /\ WF_vars(Complete) /\ WF_vars(Up)
----------------------------------------------------------------------------
TypeOK ==
    /\ st \in {"unknown", "pending", "unavailable", "lost", "error", "decided", "unsupported"}
    /\ backend \in {"up", "down"}
    /\ checkable \in BOOLEAN

\* Eventually the obligation has a verdict, or the stated reason that it
\* cannot be checked, and that does not change again.
EventuallyAnswered == <>[](st \in {"decided", "unsupported"})

\* The other direction: "unsupported" is given only for an obligation that cannot be checked.
AnswerIsRight == st = "unsupported" => ~checkable

\* Reachability: expected to be VIOLATED.
NeverUnsupported == st # "unsupported"
=============================================================================
