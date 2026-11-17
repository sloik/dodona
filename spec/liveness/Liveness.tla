------------------------------ MODULE Liveness ------------------------------
(***************************************************************************)
(* Every obligation is eventually decided (claim C22).                     *)
(*                                                                         *)
(* One obligation. Its state is unknown, pending, unavailable (the last    *)
(* attempt found the backend down) or decided. Edits, outages and lost     *)
(* runs each happen only a bounded number of times. Under the assumption   *)
(* that the kernel keeps submitting what is not decided, that the backend  *)
(* comes back, and that a run in flight eventually finishes unless it is   *)
(* lost, the obligation is eventually decided and stays decided.           *)
(*                                                                         *)
(* The bounds and the fairness conditions are the assumptions. Without     *)
(* them nothing can be promised: a backend that never returns leaves the   *)
(* obligation unknown for ever, with the reason stated.                    *)
(***************************************************************************)
EXTENDS Naturals

CONSTANTS MaxEdits, MaxOutages, MaxLosses, Mutant

VARIABLES st, backend, edits, outages, losses

vars == <<st, backend, edits, outages, losses>>

Mutants == {"none", "no_resubmit_after_unavailable", "no_resubmit_after_loss"}
ASSUME Mutant \in Mutants

Init == st = "unknown" /\ backend = "up" /\ edits = 0 /\ outages = 0 /\ losses = 0

Edit ==
    /\ edits < MaxEdits
    /\ edits' = edits + 1 /\ st' = "unknown"
    /\ UNCHANGED <<backend, outages, losses>>

Down ==
    /\ backend = "up" /\ outages < MaxOutages
    /\ backend' = "down" /\ outages' = outages + 1
    /\ UNCHANGED <<st, edits, losses>>

Up == backend = "down" /\ backend' = "up" /\ UNCHANGED <<st, edits, outages, losses>>

\* The kernel submits whatever is not decided and not in flight.
Submit ==
    /\ st \in {"unknown"} \cup (IF Mutant = "no_resubmit_after_unavailable" THEN {} ELSE {"unavailable"})
                          \cup (IF Mutant = "no_resubmit_after_loss" THEN {} ELSE {"lost"})
    /\ st' = IF backend = "up" THEN "pending" ELSE "unavailable"
    /\ UNCHANGED <<backend, edits, outages, losses>>

Complete == st = "pending" /\ st' = "decided" /\ UNCHANGED <<backend, edits, outages, losses>>

Lose ==
    /\ st = "pending" /\ losses < MaxLosses
    /\ st' = "lost" /\ losses' = losses + 1
    /\ UNCHANGED <<backend, edits, outages>>

Next == Edit \/ Down \/ Up \/ Submit \/ Complete \/ Lose

Spec == Init /\ [][Next]_vars /\ WF_vars(Submit) /\ WF_vars(Complete) /\ WF_vars(Up)

EventuallyDecided == <>[](st = "decided")
=============================================================================
