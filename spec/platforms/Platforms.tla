----------------------------- MODULE Platforms -----------------------------
(***************************************************************************)
(* Results on more than one platform (claim C15, decisions 0006 and 0008). *)
(*                                                                         *)
(* Two sets of inputs (core keys) and three platforms. A check on one core *)
(* key and one platform leaves a record; checking again may leave a second *)
(* record with the other verdict, so a platform can disagree with itself.  *)
(* Status is asked for a key on a platform:                                *)
(*                                                                         *)
(*   A platform's own records decide: one verdict is that verdict, both    *)
(*   are a conflict. Where it has none, another platform's verdict may     *)
(*   stand in, but only if policy allows stand-ins, the provider claims    *)
(*   its results do not depend on the platform, and the claim is verified  *)
(*   FOR THAT KEY: the key has one verdict on at least two platforms and   *)
(*   no platform disagrees about it. A status that rests on a stand-in is  *)
(*   reported as one.                                                      *)
(*   Reproducibility of a key differs if it has both verdicts anywhere,    *)
(*   agrees if at least two platforms have a verdict and all are the same, *)
(*   and is unknown otherwise.                                             *)
(*                                                                         *)
(* Two descriptions are kept apart on purpose. The SPECIFICATION is stated *)
(* over `recs`, every record ever made. The KERNEL works from `store`, the *)
(* verdicts it has filed for each key and platform, updated one record at  *)
(* a time. The properties say the kernel's answers, from its store, are    *)
(* the ones the records call for. A kernel that files a record wrongly, or *)
(* decides a stand-in by the wrong rule, is caught.                        *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS StandInAllowed, ProviderClaims, Mutant

VARIABLES recs, store

vars == <<recs, store>>

Keys     == {"k1", "k2"}
Plats    == {"p1", "p2", "p3"}
Verdicts == {"passed", "failed"}

Mutants == {"none", "always_stand_in", "stand_in_unverified", "stand_in_unclaimed",
            "stand_in_always_passed", "other_overrides_own", "stand_in_not_reported",
            "one_platform_reproduces", "disagreement_ignored", "verified_globally",
            "latest_only_filed", "self_disagreement_ignored"}
ASSUME Mutant \in Mutants /\ StandInAllowed \in BOOLEAN /\ ProviderClaims \in BOOLEAN

Init ==
    /\ recs = {}
    /\ store = [k \in Keys |-> [p \in Plats |-> {}]]

\* A check leaves a record. The planted defect files only the latest verdict for a platform.
Record(k, p, v) ==
    /\ [k |-> k, p |-> p, v |-> v] \notin recs
    /\ recs' = recs \cup {[k |-> k, p |-> p, v |-> v]}
    /\ store' = [store EXCEPT ![k][p] = IF Mutant = "latest_only_filed" THEN {v} ELSE @ \cup {v}]

Next == \E k \in Keys, p \in Plats, v \in Verdicts : Record(k, p, v)

Spec == Init /\ [][Next]_vars
----------------------------------------------------------------------------
(* The specification, from every record. *)

Own(k, p)        == {r.v : r \in {x \in recs : x.k = k /\ x.p = p}}
SpecRan(k)       == {p \in Plats : Own(k, p) # {}}
SpecAll(k)       == UNION {Own(k, p) : p \in Plats}
SpecVerified(k)  == Cardinality(SpecRan(k)) >= 2 /\ Cardinality(SpecAll(k)) = 1
SpecMayStand(k)  == StandInAllowed /\ ProviderClaims /\ SpecVerified(k)

SpecStatus(k, p) ==
    IF Own(k, p) = {"passed"} THEN "passed"
    ELSE IF Own(k, p) = {"failed"} THEN "failed"
    ELSE IF Own(k, p) = Verdicts THEN "conflict"
    ELSE IF SpecMayStand(k) THEN CHOOSE v \in SpecAll(k) : TRUE
    ELSE "unknown"
SpecStoodIn(k, p) == Own(k, p) = {} /\ SpecMayStand(k)
SpecRepro(k) ==
    IF SpecAll(k) = Verdicts THEN "differs"
    ELSE IF Cardinality(SpecRan(k)) >= 2 THEN "agrees" ELSE "unknown"

(* The kernel, from its store. *)

Ran(k)  == {p \in Plats : store[k][p] # {}}
All(k)  == UNION {store[k][p] : p \in Plats}
Agrees(k) == Cardinality(Ran(k)) >= 2 /\ Cardinality(All(k)) = 1
Verified(k) ==
    IF Mutant = "verified_globally"
    THEN (\E j \in Keys : Agrees(j)) /\ ~(\E j \in Keys : Cardinality(All(j)) = 2)
    ELSE Agrees(k)

MayStandIn(k) ==
    CASE Mutant = "always_stand_in" -> TRUE
      [] Mutant = "stand_in_unverified" -> StandInAllowed /\ ProviderClaims
      [] Mutant = "stand_in_unclaimed"  -> StandInAllowed /\ Verified(k)
      [] OTHER -> StandInAllowed /\ ProviderClaims /\ Verified(k)

UsesStandIn(k, p) == store[k][p] = {} /\ MayStandIn(k) /\ Ran(k) # {}

Status(k, p) ==
    LET own == store[k][p]
        other == UNION {store[k][q] : q \in Ran(k) \ {p}}
    IN IF own # {} /\ Mutant = "other_overrides_own" /\ other # {} THEN CHOOSE v \in other : TRUE
       ELSE IF own = {"passed"} THEN "passed"
       ELSE IF own = {"failed"} THEN "failed"
       ELSE IF own = Verdicts THEN (IF Mutant = "self_disagreement_ignored" THEN "passed" ELSE "conflict")
       ELSE IF UsesStandIn(k, p) THEN (IF Mutant = "stand_in_always_passed" THEN "passed" ELSE CHOOSE v \in All(k) : TRUE)
       ELSE "unknown"

ReportedStandIn(k, p) == UsesStandIn(k, p) /\ Mutant # "stand_in_not_reported"

Repro(k) ==
    IF All(k) = Verdicts THEN (IF Mutant = "disagreement_ignored" THEN "agrees" ELSE "differs")
    ELSE IF Cardinality(Ran(k)) >= 2 THEN "agrees"
    ELSE IF Mutant = "one_platform_reproduces" /\ Ran(k) # {} THEN "agrees" ELSE "unknown"
----------------------------------------------------------------------------
TypeOK ==
    /\ recs \subseteq [k : Keys, p : Plats, v : Verdicts]
    /\ store \in [Keys -> [Plats -> SUBSET Verdicts]]

\* Every status is the one the records call for, and only a stand-in the rule allows is used.
StatusMatches == \A k \in Keys, p \in Plats : Status(k, p) = SpecStatus(k, p)

\* A status that rests on another platform's record is reported as one, and no other is.
StandInIsReported == \A k \in Keys, p \in Plats : ReportedStandIn(k, p) = SpecStoodIn(k, p)

\* Reproducibility is the one the records call for.
ReproMatches == \A k \in Keys : Repro(k) = SpecRepro(k)

\* Reachability: expected to be VIOLATED.
NeverStoodIn == \A k \in Keys, p \in Plats : ~SpecStoodIn(k, p)
NeverSelfConflict == \A k \in Keys, p \in Plats : SpecStatus(k, p) # "conflict"
=============================================================================
