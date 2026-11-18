------------------------------ MODULE Attempts ------------------------------
(***************************************************************************)
(* Trying a judgement again (claim C35, decision 0024).                    *)
(*                                                                         *)
(* A checker takes a ticket before each attempt at judging something. An   *)
(* attempt is open until it is closed as agreed or refused; one that is    *)
(* never closed counts as a failure. Attempts belong to a LINE: the same   *)
(* criterion of the same intent. The thing being judged may change along   *)
(* the line, and the kernel cannot tell a real fix from a trivial change   *)
(* made to get a fresh try. So, as decision 0024 says, a change of target  *)
(* resets neither the count nor the cap. It does reset the result, which   *)
(* is about the current target; that is a reading of 0024, not its text:  *)
(*                                                                         *)
(*   On the current target the worst result counts.                        *)
(*   Along the whole line every attempt is counted, and an agreement that  *)
(*   follows (in ticket order) any attempt that did not agree is "retried":*)
(*   flagged, and the separation of the act is capped at "helper" and      *)
(*   never raised above what it claimed. "Shopped" is the same on one      *)
(*   target; it is reported too, and implies retried.                      *)
(*                                                                         *)
(* Two descriptions are kept apart on purpose. The SPECIFICATION is stated *)
(* over `log`, every event in the order it happened. The KERNEL works from *)
(* its records, `attempts`, as a real kernel does: one record per ticket,  *)
(* updated in place. The properties say the kernel's answers, worked out   *)
(* from its records, are the ones the history calls for. A kernel that     *)
(* keeps its records wrongly (closes the wrong ticket, files an attempt    *)
(* under the target it has when it closes, forgets attempts when the       *)
(* target changes) is caught even though its answers are computed by the  *)
(* right rule.                                                             *)
(*                                                                         *)
(* Not covered: attempts made without taking a ticket, which leave no      *)
(* record.                                                                 *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS MaxAttempts, Claimed, Mutant

VARIABLES target, attempts, taken, log

vars == <<target, attempts, taken, log>>

Levels == {"self", "helper", "apart"}
Rank(l) == CASE l = "self" -> 0 [] l = "helper" -> 1 [] l = "apart" -> 2

Mutants == {"none", "latest_only", "open_ignored", "flag_does_not_cap", "flag_missed",
            "change_hides_history", "cap_raises", "cap_on_shopping_only", "close_latest_open",
            "filed_at_close", "retried_only_on_same_target", "retried_hidden"}
ASSUME Mutant \in Mutants /\ MaxAttempts \in Nat /\ Claimed \in Levels

Init == target = 0 /\ attempts = {} /\ taken = 0 /\ log = <<>>

Take ==
    /\ taken < MaxAttempts
    /\ taken' = taken + 1
    /\ attempts' = attempts \cup {[n |-> taken + 1, target |-> target, outcome |-> "open"]}
    /\ log' = Append(log, [ev |-> "take", n |-> taken + 1, target |-> target, outcome |-> "open"])
    /\ UNCHANGED target

\* The checker closes ticket t. The planted defect closes the latest open attempt instead,
\* whatever ticket was named; another files the attempt under the target as it is when it closes.
Close(t, o) ==
    /\ \E a \in attempts : a.n = t /\ a.outcome = "open"
    /\ LET named  == CHOOSE a \in attempts : a.n = t
           open   == {a \in attempts : a.outcome = "open"}
           latest == CHOOSE a \in open : \A b \in open : b.n <= a.n
           which  == IF Mutant = "close_latest_open" THEN latest ELSE named
           closed == IF Mutant = "filed_at_close" THEN [which EXCEPT !.outcome = o, !.target = target]
                     ELSE [which EXCEPT !.outcome = o]
       IN attempts' = (attempts \ {which}) \cup {closed}
    /\ log' = Append(log, [ev |-> "close", n |-> t, target |-> target, outcome |-> o])
    /\ UNCHANGED <<target, taken>>

\* The thing being judged changes. Nothing in the record says whether the change was a real fix.
\* The planted defect forgets the attempts on the old target.
ChangeTarget ==
    /\ target < 2
    /\ target' = target + 1
    /\ attempts' = IF Mutant = "change_hides_history" THEN {a \in attempts : a.target # target} ELSE attempts
    /\ log' = Append(log, [ev |-> "change", n |-> 0, target |-> target + 1, outcome |-> "open"])
    /\ UNCHANGED taken

Next ==
    \/ Take
    \/ \E t \in 1..MaxAttempts, o \in {"agreed", "refused"} : Close(t, o)
    \/ ChangeTarget

Spec == Init /\ [][Next]_vars
----------------------------------------------------------------------------
(* The specification, from the history alone. *)

Tickets == {log[i].n : i \in {j \in 1..Len(log) : log[j].ev = "take"}}
TakenOn(t) == log[CHOOSE i \in 1..Len(log) : log[i].ev = "take" /\ log[i].n = t].target
\* An attempt's outcome is the last close event that named its ticket, or open.
OutcomeOf(t) ==
    LET closes == {i \in 1..Len(log) : log[i].ev = "close" /\ log[i].n = t}
    IN IF closes = {} THEN "open" ELSE log[CHOOSE i \in closes : \A j \in closes : j <= i].outcome

SpecCurrent == {t \in Tickets : TakenOn(t) = target}
SpecResult ==
    IF SpecCurrent = {} THEN "none"
    ELSE IF \A t \in SpecCurrent : OutcomeOf(t) = "agreed" THEN "agreed" ELSE "refused"
SpecShopped ==
    \E a, b \in SpecCurrent : a < b /\ OutcomeOf(a) # "agreed" /\ OutcomeOf(b) = "agreed"
SpecRetried ==
    \E a, b \in Tickets : a < b /\ OutcomeOf(a) # "agreed" /\ OutcomeOf(b) = "agreed"
SpecGranted ==
    IF SpecRetried /\ Rank(Claimed) > Rank("helper") THEN "helper" ELSE Claimed

(* The kernel, from its records. *)

Current == {a \in attempts : a.target = target}
Latest == CHOOSE a \in Current : \A b \in Current : b.n <= a.n

Result ==
    IF Current = {} THEN "none"
    ELSE CASE Mutant = "latest_only" -> IF Latest.outcome = "agreed" THEN "agreed" ELSE "refused"
           [] Mutant = "open_ignored" ->
                 IF \E a \in Current : a.outcome = "refused" THEN "refused"
                 ELSE IF \E a \in Current : a.outcome = "agreed" THEN "agreed" ELSE "refused"
           [] OTHER -> IF \A a \in Current : a.outcome = "agreed" THEN "agreed" ELSE "refused"

KernelShopped ==
    IF Mutant = "flag_missed" THEN FALSE
    ELSE \E a, b \in Current : a.n < b.n /\ a.outcome # "agreed" /\ b.outcome = "agreed"
\* What the kernel works out, and what it reports. The two planted defects in the report leave
\* the cap alone, so each isolates the flag.
Retried == \E a, b \in attempts : a.n < b.n /\ a.outcome # "agreed" /\ b.outcome = "agreed"
KernelRetried ==
    CASE Mutant = "retried_only_on_same_target" -> KernelShopped
      [] Mutant = "retried_hidden" -> FALSE
      [] OTHER -> Retried
KernelCount == Cardinality(attempts)

\* The separation level after the cap. Capping lowers a level; it never raises one.
Granted ==
    LET capped == IF Mutant = "cap_on_shopping_only" THEN KernelShopped ELSE Retried
    IN IF capped /\ Mutant # "flag_does_not_cap"
       THEN (IF Mutant = "cap_raises" THEN "helper"
             ELSE IF Rank(Claimed) > Rank("helper") THEN "helper" ELSE Claimed)
       ELSE Claimed
----------------------------------------------------------------------------
TypeOK ==
    /\ target \in 0..2 /\ taken \in 0..MaxAttempts
    /\ \A a \in attempts : a.n \in 1..MaxAttempts /\ a.target \in 0..2 /\ a.outcome \in {"open", "agreed", "refused"}
    /\ Len(log) <= MaxAttempts * 3 + 2

\* The kernel's result on the current target is the one the history calls for.
WorstCounts == Result = SpecResult

\* Retrying is reported along the whole line, shopping on the current target, and
\* the level granted is the one the history calls for: helper at most after a retry,
\* never above what was claimed.
RetryIsCapped ==
    /\ KernelRetried = SpecRetried
    /\ KernelShopped = SpecShopped
    /\ Granted = SpecGranted

\* Every attempt along the line is counted.
HistoryIsKept == KernelCount = Cardinality(Tickets)

\* Reachability: expected to be VIOLATED.
NeverAgreed  == SpecResult # "agreed"
NeverShopped == ~SpecShopped
\* An agreement on a changed target after a refusal on the old one: not shopped,
\* and still retried and capped.
NeverRetriedAcrossChange == ~(SpecRetried /\ ~SpecShopped /\ SpecResult = "agreed")
=============================================================================
