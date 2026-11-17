----------------------------- MODULE Platforms -----------------------------
(***************************************************************************)
(* Results on more than one platform (claim C15, decisions 0006 and 0008). *)
(*                                                                         *)
(* Two sets of inputs (core keys) and three platforms. A check on one core *)
(* key and one platform leaves one record. Status is asked for a platform. *)
(* A platform's own record always decides. Where it has none, a record     *)
(* from another platform may stand in, but only if the provider claims its *)
(* results do not depend on the platform, policy allows stand-ins, and the *)
(* claim has been verified. A status that rests on a stand-in is reported  *)
(* as one.                                                                 *)
(*                                                                         *)
(* "Verified" here means: some core key has the same verdict on at least   *)
(* two platforms, and no core key has different verdicts on two. One       *)
(* agreeing sample is enough in this model. That is a weak notion, and     *)
(* the claim says so.                                                      *)
(*                                                                         *)
(* Reproducibility of a core key is "failed" if two platforms disagree,    *)
(* "passed" if at least two have run and all agree, otherwise "unknown".   *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS StandInAllowed, ProviderClaims, Mutant

VARIABLE rec

Keys  == {"k1", "k2"}
Plats == {"p1", "p2", "p3"}

Mutants == {"none", "always_stand_in", "stand_in_unverified", "stand_in_unclaimed",
            "stand_in_always_passed", "other_overrides_own", "stand_in_not_reported",
            "one_platform_reproduces", "disagreement_ignored"}
ASSUME Mutant \in Mutants /\ StandInAllowed \in BOOLEAN /\ ProviderClaims \in BOOLEAN

Init == rec = [k \in Keys |-> [p \in Plats |-> "none"]]

Record(k, p, v) ==
    /\ rec[k][p] = "none"
    /\ rec' = [rec EXCEPT ![k][p] = v]

Next == \E k \in Keys, p \in Plats, v \in {"passed", "failed"} : Record(k, p, v)

Spec == Init /\ [][Next]_rec
----------------------------------------------------------------------------
Ran(k)      == {p \in Plats : rec[k][p] # "none"}
Verdicts(k) == {rec[k][p] : p \in Ran(k)}
Agree(k)    == Cardinality(Ran(k)) >= 2 /\ Cardinality(Verdicts(k)) = 1
Disagree(k) == Cardinality(Verdicts(k)) = 2

ClaimVerified == (\E k \in Keys : Agree(k)) /\ ~(\E k \in Keys : Disagree(k))

MayStandIn ==
    CASE Mutant \in {"always_stand_in", "other_overrides_own"} -> TRUE
      [] Mutant = "stand_in_unverified" -> StandInAllowed /\ ProviderClaims
      [] Mutant = "stand_in_unclaimed"  -> StandInAllowed /\ ClaimVerified
      [] OTHER -> StandInAllowed /\ ProviderClaims /\ ClaimVerified

\* When a stand-in is allowed no two platforms disagree, so every record of a
\* key has the same verdict and it does not matter which one stands in.
Borrowed(k) == CHOOSE v \in Verdicts(k) : TRUE

UsesStandIn(k, p) ==
    IF Mutant = "other_overrides_own"
    THEN MayStandIn /\ Ran(k) \ {p} # {}
    ELSE rec[k][p] = "none" /\ MayStandIn /\ Ran(k) # {}

Status(k, p) ==
    IF UsesStandIn(k, p)
    THEN (IF Mutant = "stand_in_always_passed" THEN "passed"
          ELSE IF Mutant = "other_overrides_own" THEN (CHOOSE v \in {rec[k][q] : q \in Ran(k) \ {p}} : TRUE)
          ELSE Borrowed(k))
    ELSE IF rec[k][p] # "none" THEN rec[k][p] ELSE "unknown"

\* What the report says about where a status came from.
ReportedStandIn(k, p) == UsesStandIn(k, p) /\ Mutant # "stand_in_not_reported"

Repro(k) ==
    IF Disagree(k) THEN (IF Mutant = "disagreement_ignored" THEN "passed" ELSE "failed")
    ELSE IF Agree(k) THEN "passed"
    ELSE IF Mutant = "one_platform_reproduces" /\ Ran(k) # {} THEN "passed" ELSE "unknown"
----------------------------------------------------------------------------
TypeOK == rec \in [Keys -> [Plats -> {"none", "passed", "failed"}]]

\* A platform's own record decides its status.
OwnRecordDecides ==
    \A k \in Keys, p \in Plats : rec[k][p] # "none" => Status(k, p) = rec[k][p]

\* A status with no record of its own needs a provider's claim, policy's
\* permission and a verified claim, and it is some other platform's verdict.
StandInIsEarned ==
    \A k \in Keys, p \in Plats :
        (rec[k][p] = "none" /\ Status(k, p) # "unknown") =>
            /\ StandInAllowed /\ ProviderClaims /\ ClaimVerified
            /\ \E q \in Ran(k) : Status(k, p) = rec[k][q]

\* A status that rests on another platform's record is reported as doing so.
StandInIsReported ==
    \A k \in Keys, p \in Plats :
        (rec[k][p] = "none" /\ Status(k, p) # "unknown") => ReportedStandIn(k, p)

\* Reproducibility passes only with at least two agreeing platforms, and fails
\* on any disagreement.
ReproSound ==
    \A k \in Keys : /\ Repro(k) = "passed" => Agree(k)
                    /\ Disagree(k) => Repro(k) = "failed"

\* Reachability.
NeverStoodIn == \A k \in Keys, p \in Plats : ~(rec[k][p] = "none" /\ Status(k, p) # "unknown")
=============================================================================
