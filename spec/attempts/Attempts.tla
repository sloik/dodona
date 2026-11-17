------------------------------ MODULE Attempts ------------------------------
(***************************************************************************)
(* Trying a judgement again (claim C35, decision 0024).                    *)
(*                                                                         *)
(* A checker takes a ticket before each attempt at judging a target. The   *)
(* attempt is open until it is closed as agreed or refused. An attempt     *)
(* that is never closed stays open and counts as a failure. On a target    *)
(* that has not changed, the worst result counts. An agreement that comes  *)
(* after an earlier attempt that did not agree is flagged as shopping, and *)
(* caps the separation of the act at "helper".                             *)
(*                                                                         *)
(* Not covered: attempts made without taking a ticket, which leave no      *)
(* trace and cannot be modelled from the record.                           *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS MaxAttempts, Mutant

VARIABLES target, attempts, taken

vars == <<target, attempts, taken>>

Mutants == {"none", "latest_only", "open_ignored", "flag_does_not_cap", "flag_missed"}
ASSUME Mutant \in Mutants /\ MaxAttempts \in Nat

Init == target = 0 /\ attempts = {} /\ taken = 0

Take ==
    /\ taken < MaxAttempts
    /\ taken' = taken + 1
    /\ attempts' = attempts \cup {[n |-> taken + 1, target |-> target, outcome |-> "open"]}
    /\ UNCHANGED target

Close(a, o) ==
    /\ a \in attempts /\ a.outcome = "open"
    /\ attempts' = (attempts \ {a}) \cup {[a EXCEPT !.outcome = o]}
    /\ UNCHANGED <<target, taken>>

\* The thing being judged really changes.
ChangeTarget == target = 0 /\ target' = 1 /\ UNCHANGED <<attempts, taken>>

Next ==
    \/ Take
    \/ \E a \in attempts, o \in {"agreed", "refused"} : Close(a, o)
    \/ ChangeTarget

Spec == Init /\ [][Next]_vars
----------------------------------------------------------------------------
Current == {a \in attempts : a.target = target}

Latest == CHOOSE a \in Current : \A b \in Current : b.n <= a.n

Result ==
    IF Current = {} THEN "none"
    ELSE CASE Mutant = "latest_only" -> IF Latest.outcome = "agreed" THEN "agreed" ELSE "refused"
           [] Mutant = "open_ignored" ->
                 IF \E a \in Current : a.outcome = "refused" THEN "refused"
                 ELSE IF \E a \in Current : a.outcome = "agreed" THEN "agreed" ELSE "refused"
           [] OTHER -> IF \A a \in Current : a.outcome = "agreed" THEN "agreed" ELSE "refused"

\* An agreement after an earlier attempt on the same target that did not agree.
ReallyShopped ==
    \E a, b \in Current : a.n < b.n /\ a.outcome # "agreed" /\ b.outcome = "agreed"

ReportShopped == IF Mutant = "flag_missed" THEN FALSE ELSE ReallyShopped
ReportCap     == IF ReportShopped /\ Mutant # "flag_does_not_cap" THEN "helper" ELSE "no-cap"

\* The worst result counts, and an attempt left open counts as a failure.
WorstCounts == Result = "agreed" => \A a \in Current : a.outcome = "agreed"

\* Shopping is always flagged, and the flag always caps the level.
ShoppingIsFlagged == ReallyShopped => ReportShopped /\ ReportCap = "helper"

\* Reachability: expected to be VIOLATED.
NeverAgreed  == Result # "agreed"
NeverShopped == ~ReallyShopped
=============================================================================
