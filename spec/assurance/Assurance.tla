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
            "empty_is_shown", "fold_skips_middle", "failed_reported_none_planted", "observed_above_sampled"}
ASSUME Mutant \in Mutants

Init ==
    /\ links \in [Links -> Levels \cup {"unreported"}]
    /\ planted \in SUBSET Defects
    /\ defect \in [Defects -> {"passed", "failed", "unknown"}]

Next == UNCHANGED vars
Spec == Init /\ [][Next]_vars

Min(S) == CHOOSE x \in S : \A y \in S : x <= y

(* The specification: the weakest link, with a link nobody reported counting as nothing; and
   "shown able to fail" exactly when at least one defect was planted and every one was caught. *)
TrueShown == Min({Rank(links[l]) : l \in Links})
SpecNonVacuous ==
    IF planted = {} THEN "none-planted"
    ELSE IF \A m \in planted : defect[m] = "passed" THEN "shown" ELSE "not-shown"

Reported == {l \in Links : links[l] # "unreported"}

(* The kernel: it goes along the chain one link at a time, keeping the weaker of the level it has
   and the next link, as code over a list does. It compares levels by its own table of ranks and
   answers with a level's NAME, which is then read on the true scale. A wrong table shows only
   where it makes the kernel name a different level. *)
Name(l) == IF l = "unreported" THEN "none" ELSE l
KRank(l) == IF Mutant = "observed_above_sampled" /\ l = "observed" THEN 3
            ELSE IF Mutant = "observed_above_sampled" /\ l = "sampled" THEN 2 ELSE Rank(l)
Weaker(a, b) == IF KRank(a) <= KRank(b) THEN a ELSE b
Folded ==
    IF Mutant = "fold_skips_middle"
    THEN Weaker(Name(links["spec-to-code"]), Name(links["runs-to-world"]))
    ELSE Weaker(Weaker(Name(links["spec-to-code"]), Name(links["code-to-runs"])), Name(links["runs-to-world"]))
LevelAt(r) == CHOOSE l \in Levels : Rank(l) = r

ShownName ==
    CASE Mutant = "average" ->
            LevelAt((Rank(links["spec-to-code"]) + Rank(links["code-to-runs"]) + Rank(links["runs-to-world"])) \div 3)
      [] Mutant = "ignore_unreported" ->
            IF Reported = {} THEN "none" ELSE LevelAt(Min({Rank(links[l]) : l \in Reported}))
      [] Mutant = "always_nothing" -> "none"
      [] OTHER -> Folded
ShownRank == Rank(ShownName)

NonVacuous ==
    IF planted = {} THEN "none-planted"
    ELSE IF \A m \in planted : defect[m] = "passed" THEN "shown" ELSE "not-shown"

Reported == {l \in Links : links[l] # "unreported"}

(* The kernel: it goes along the chain one link at a time, keeping the weaker of what it has and
   the next link, as code over a list does; and it reads the scale from its own table of ranks. *)
KRank(l) == IF Mutant = "observed_above_sampled" /\ l = "observed" THEN 3
            ELSE IF Mutant = "observed_above_sampled" /\ l = "sampled" THEN 2 ELSE Rank(l)
Weaker(a, b) == IF a <= b THEN a ELSE b
Folded ==
    IF Mutant = "fold_skips_middle"
    THEN Weaker(KRank(links["spec-to-code"]), KRank(links["runs-to-world"]))
    ELSE Weaker(Weaker(KRank(links["spec-to-code"]), KRank(links["code-to-runs"])), KRank(links["runs-to-world"]))

ShownRank ==
    CASE Mutant = "average" ->
            (Rank(links["spec-to-code"]) + Rank(links["code-to-runs"]) + Rank(links["runs-to-world"])) \div 3
      [] Mutant = "ignore_unreported" ->
            IF Reported = {} THEN 0 ELSE Min({Rank(links[l]) : l \in Reported})
      [] Mutant = "always_nothing" -> 0
      [] OTHER -> Folded

NonVacuous ==
    IF planted = {} THEN (IF Mutant = "empty_is_shown" THEN "shown" ELSE "none-planted")
    ELSE IF Mutant = "failed_reported_none_planted" /\ \E m \in planted : defect[m] = "failed" THEN "none-planted"
    ELSE IF \A m \in planted : defect[m] = "passed"
                                \/ (Mutant = "unknown_defect_counts" /\ defect[m] = "unknown")
         THEN "shown" ELSE "not-shown"
----------------------------------------------------------------------------
TypeOK ==
    /\ links \in [Links -> Levels \cup {"unreported"}]
    /\ planted \subseteq Defects
    /\ defect \in [Defects -> {"passed", "failed", "unknown"}]

\* The kernel's level, worked out one link at a time from its own scale, is the weakest link.
WeakestLink == ShownRank = TrueShown

\* What the kernel reports about planted defects is what the specification says, in every case:
\* not "shown" when one was missed, not "none planted" when some were.
NonVacuitySound == NonVacuous = SpecNonVacuous

\* Reachability: expected to be VIOLATED.
NeverProven == ShownRank # 5
NeverShown  == NonVacuous # "shown"
=============================================================================
