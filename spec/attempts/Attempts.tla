------------------------------ MODULE Attempts ------------------------------
(***************************************************************************)
(* Trying a judgement again (claim C35, decision 0024).                    *)
(*                                                                         *)
(* A checker takes a ticket before each attempt at judging something. An   *)
(* attempt is open until it is closed as agreed or refused; one that is    *)
(* never closed counts as a failure. Attempts belong to a LINE: the same   *)
(* criterion of the same intent. The thing being judged may change along   *)
(* the line, and the kernel cannot tell a real fix from a trivial change   *)
(* made to get a fresh try. So there are two rules:                        *)
(*                                                                         *)
(*   On the current target the worst result counts, and an agreement that  *)
(*   follows an attempt that did not agree is "shopped": flagged, and the  *)
(*   separation of the act is capped at "helper".                          *)
(*                                                                         *)
(*   Along the whole line, every attempt is counted and an agreement that  *)
(*   follows any earlier attempt that did not agree is reported as         *)
(*   "retried", whatever happened to the target in between. Changing the   *)
(*   target gets a new answer. It does not hide the history.               *)
(*                                                                         *)
(* Not covered: attempts made without taking a ticket, which leave no      *)
(* record.                                                                 *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS MaxAttempts, Claimed, Mutant

VARIABLES target, attempts, taken

vars == <<target, attempts, taken>>

Levels == {"self", "helper", "apart"}
Rank(l) == CASE l = "self" -> 0 [] l = "helper" -> 1 [] l = "apart" -> 2

Mutants == {"none", "latest_only", "open_ignored", "flag_does_not_cap", "flag_missed",
            "change_hides_history", "cap_raises"}
ASSUME Mutant \in Mutants /\ MaxAttempts \in Nat /\ Claimed \in Levels

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

\* The thing being judged changes. Nothing in the record says whether the
\* change was a real fix.
ChangeTarget == target < 2 /\ target' = target + 1 /\ UNCHANGED <<attempts, taken>>

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

\* Ground truth, straight from the attempts.
ReallyShopped ==
    \E a, b \in Current : a.n < b.n /\ a.outcome # "agreed" /\ b.outcome = "agreed"
ReallyRetried ==
    \E a, b \in attempts : a.n < b.n /\ a.outcome # "agreed" /\ b.outcome = "agreed"

\* What the kernel reports.
ReportShopped == IF Mutant = "flag_missed" THEN FALSE ELSE ReallyShopped
ReportRetried == IF Mutant = "change_hides_history" THEN ReallyShopped ELSE ReallyRetried
ReportCount   == IF Mutant = "change_hides_history" THEN Cardinality(Current) ELSE Cardinality(attempts)

\* The separation level after the cap. Capping lowers a level; it never raises one.
Granted ==
    IF ReportShopped /\ Mutant # "flag_does_not_cap"
    THEN (IF Mutant = "cap_raises" THEN "helper"
          ELSE IF Rank(Claimed) > Rank("helper") THEN "helper" ELSE Claimed)
    ELSE Claimed
----------------------------------------------------------------------------
TypeOK ==
    /\ target \in 0..2 /\ taken \in 0..MaxAttempts
    /\ \A a \in attempts : a.outcome \in {"open", "agreed", "refused"}

\* The worst result on the current target counts; an open attempt is a failure.
WorstCounts == Result = "agreed" => \A a \in Current : a.outcome = "agreed"

\* Shopping is flagged, and a flagged act is graded "helper" at most and never
\* above what it claimed.
ShoppingIsCapped ==
    /\ ReallyShopped => ReportShopped /\ Rank(Granted) <= Rank("helper")
    /\ Rank(Granted) <= Rank(Claimed)

\* The history along the line is reported whatever happened to the target.
HistoryIsKept ==
    /\ ReportCount = taken
    /\ ReportRetried <=> ReallyRetried

\* Reachability: expected to be VIOLATED.
NeverAgreed  == Result # "agreed"
NeverShopped == ~ReallyShopped
\* An agreement on a changed target after a refusal on the old one: not
\* shopped, and still reported as retried.
NeverRetriedAcrossChange == ~(ReallyRetried /\ ~ReallyShopped /\ Result = "agreed")
=============================================================================
