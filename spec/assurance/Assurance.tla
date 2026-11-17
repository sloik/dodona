----------------------------- MODULE Assurance -----------------------------
(***************************************************************************)
(* The shown level of a criterion and whether a check is non-vacuous       *)
(* (claims C24, C19 and C31).                                              *)
(*                                                                         *)
(* These are pure rules, so the model has no steps: every combination of   *)
(* inputs is an initial state, and the checker examines them all.          *)
(*                                                                         *)
(* Three evidence links each have a level or nothing reported. Two planted *)
(* defects each have a status, and either may be absent.                   *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANT Mutant

VARIABLES links, planted, defect

vars == <<links, planted, defect>>

Links  == {"spec-to-code", "code-to-runs", "runs-to-world"}
Levels == {"none", "asserted", "observed", "sampled", "bounded", "proven"}
Rank(l) == CASE l = "unreported" -> 0 [] l = "none" -> 0 [] l = "asserted" -> 1
             [] l = "observed" -> 2 [] l = "sampled" -> 3 [] l = "bounded" -> 4 [] l = "proven" -> 5
Defects == {"m1", "m2"}

Mutants == {"none", "average", "ignore_unreported", "always_nothing", "unknown_defect_counts",
            "empty_is_shown"}
ASSUME Mutant \in Mutants

Init ==
    /\ links \in [Links -> Levels \cup {"unreported"}]
    /\ planted \in SUBSET Defects
    /\ defect \in [Defects -> {"passed", "failed", "unknown"}]

Next == UNCHANGED vars
Spec == Init /\ [][Next]_vars

Min(S) == CHOOSE x \in S : \A y \in S : x <= y

\* The rule: the weakest link, with a link nobody reported counting as nothing.
TrueShown == Min({Rank(links[l]) : l \in Links})

Reported == {l \in Links : links[l] # "unreported"}

ShownRank ==
    CASE Mutant = "average" ->
            (Rank(links["spec-to-code"]) + Rank(links["code-to-runs"]) + Rank(links["runs-to-world"])) \div 3
      [] Mutant = "ignore_unreported" ->
            IF Reported = {} THEN 0 ELSE Min({Rank(links[l]) : l \in Reported})
      [] Mutant = "always_nothing" -> 0
      [] OTHER -> TrueShown

NonVacuous ==
    IF planted = {} THEN (IF Mutant = "empty_is_shown" THEN "shown" ELSE "none-planted")
    ELSE IF \A m \in planted : defect[m] = "passed"
                                \/ (Mutant = "unknown_defect_counts" /\ defect[m] = "unknown")
         THEN "shown" ELSE "not-shown"
----------------------------------------------------------------------------
\* The shown level is never above any link, and an unreported link is nothing.
WeakestLink == \A l \in Links : ShownRank <= Rank(links[l])

\* The shown level is not lower than it has to be either.
NotUnderstated == ShownRank = TrueShown

\* "Shown" only when there is at least one planted defect and every one was caught.
NonVacuitySound ==
    NonVacuous = "shown" => planted # {} /\ \A m \in planted : defect[m] = "passed"

\* Reachability: expected to be VIOLATED.
NeverProven == ShownRank # 5
NeverShown  == NonVacuous # "shown"
=============================================================================
