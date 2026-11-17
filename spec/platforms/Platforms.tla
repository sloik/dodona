----------------------------- MODULE Platforms -----------------------------
(***************************************************************************)
(* Results on more than one platform (claim C15, decisions 0006 and 0008). *)
(*                                                                         *)
(* Two sets of inputs (core keys) and two platforms. A check on one core   *)
(* key and one platform leaves one record. Status is asked for a platform  *)
(* and uses that platform's own record. A record from the other platform   *)
(* may stand in only if policy allows it and the provider's claim to be    *)
(* platform-independent has been verified: some core key has agreeing      *)
(* records on both platforms, and none has disagreeing ones.               *)
(*                                                                         *)
(* Reproducibility of a core key is "failed" if its two platforms          *)
(* disagree, "passed" if they agree, and "unknown" with fewer than two.    *)
(***************************************************************************)
EXTENDS Naturals

CONSTANTS StandInAllowed, Mutant

VARIABLE rec

Keys  == {"k1", "k2"}
Plats == {"p1", "p2"}
Other(p) == IF p = "p1" THEN "p2" ELSE "p1"

Mutants == {"none", "always_stand_in", "stand_in_unverified", "one_platform_reproduces",
            "disagreement_ignored"}
ASSUME Mutant \in Mutants /\ StandInAllowed \in BOOLEAN

Init == rec = [k \in Keys |-> [p \in Plats |-> "none"]]

Record(k, p, v) ==
    /\ rec[k][p] = "none"
    /\ rec' = [rec EXCEPT ![k][p] = v]

Next == \E k \in Keys, p \in Plats, v \in {"passed", "failed"} : Record(k, p, v)

Spec == Init /\ [][Next]_rec
----------------------------------------------------------------------------
Both(k)     == rec[k]["p1"] # "none" /\ rec[k]["p2"] # "none"
Agree(k)    == Both(k) /\ rec[k]["p1"] = rec[k]["p2"]
Disagree(k) == Both(k) /\ rec[k]["p1"] # rec[k]["p2"]

ClaimVerified == (\E k \in Keys : Agree(k)) /\ ~(\E k \in Keys : Disagree(k))

MayStandIn ==
    CASE Mutant = "always_stand_in" -> TRUE
      [] Mutant = "stand_in_unverified" -> StandInAllowed
      [] OTHER -> StandInAllowed /\ ClaimVerified

Status(k, p) ==
    IF rec[k][p] # "none" THEN rec[k][p]
    ELSE IF MayStandIn /\ rec[k][Other(p)] # "none" THEN rec[k][Other(p)]
    ELSE "unknown"

StoodIn(k, p) == rec[k][p] = "none" /\ Status(k, p) # "unknown"

Repro(k) ==
    IF Disagree(k) THEN (IF Mutant = "disagreement_ignored" THEN "passed" ELSE "failed")
    ELSE IF Agree(k) THEN "passed"
    ELSE IF Mutant = "one_platform_reproduces" /\ (rec[k]["p1"] # "none" \/ rec[k]["p2"] # "none")
         THEN "passed" ELSE "unknown"

\* A status that rests on another platform's record needs policy and a verified claim.
StandInIsEarned ==
    \A k \in Keys, p \in Plats : StoodIn(k, p) => StandInAllowed /\ ClaimVerified

\* Reproducibility passes only with two agreeing platforms, and fails on any disagreement.
ReproSound ==
    \A k \in Keys : /\ Repro(k) = "passed" => Agree(k)
                    /\ Disagree(k) => Repro(k) = "failed"

\* Reachability.
NeverStoodIn == \A k \in Keys, p \in Plats : ~StoodIn(k, p)
=============================================================================
