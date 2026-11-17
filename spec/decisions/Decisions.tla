----------------------------- MODULE Decisions -----------------------------
(***************************************************************************)
(* A decision is flagged when what it governs changes (claim C16).         *)
(*                                                                         *)
(* Three named definitions. Each name has a content identity, or is gone   *)
(* (identity 0). A decision governs the names n1 and n2. What it must be   *)
(* compared against is the content each governed name had when the         *)
(* decision was last REVIEWED. The model keeps that in `reviewed`, which   *)
(* only a review changes, separately from `recorded`, which is whatever    *)
(* the kernel has stored. A kernel that quietly updates its stored value   *)
(* when a definition is edited makes the two differ, and never flags.      *)
(*                                                                         *)
(* Not covered: renaming, and more than one decision.                      *)
(***************************************************************************)
EXTENDS Naturals

CONSTANT Mutant

VARIABLES ident, recorded, reviewed

vars == <<ident, recorded, reviewed>>

Names   == {"n1", "n2", "n3"}
Governs == {"n1", "n2"}
Idents  == {0, 1, 2}

Mutants == {"none", "identities_without_names", "gone_is_not_flagged", "refresh_on_edit",
            "first_name_only"}
ASSUME Mutant \in Mutants

Init ==
    /\ ident \in [Names -> {1, 2}]
    /\ recorded = [n \in Governs |-> ident[n]]
    /\ reviewed = [n \in Governs |-> ident[n]]

Edit(n, h) ==
    /\ h # ident[n]
    /\ ident' = [ident EXCEPT ![n] = h]
    /\ recorded' = IF Mutant = "refresh_on_edit" /\ n \in Governs
                   THEN [recorded EXCEPT ![n] = h] ELSE recorded
    /\ UNCHANGED reviewed

\* The decision is reviewed against what its names are now. Nothing to review
\* against if a governed name is gone.
Review ==
    /\ \A n \in Governs : ident[n] # 0
    /\ \E n \in Governs : reviewed[n] # ident[n]
    /\ reviewed' = [n \in Governs |-> ident[n]]
    /\ recorded' = [n \in Governs |-> ident[n]]
    /\ UNCHANGED ident

Next == (\E n \in Names, h \in Idents : Edit(n, h)) \/ Review

Spec == Init /\ [][Next]_vars
----------------------------------------------------------------------------
TypeOK == ident \in [Names -> Idents] /\ recorded \in [Governs -> Idents] /\ reviewed \in [Governs -> Idents]

\* Ground truth, from what was reviewed: some governed name no longer has the
\* content the decision was reviewed against.
ShouldFlag == \E n \in Governs : ident[n] # reviewed[n]

\* What the kernel reports, from what it has stored.
Flag ==
    CASE Mutant = "identities_without_names" ->
            \E n \in Governs : ~\E m \in Names : ident[m] = recorded[n]
      [] Mutant = "gone_is_not_flagged" ->
            \E n \in Governs : ident[n] # recorded[n] /\ ident[n] # 0
      [] Mutant = "first_name_only" -> ident["n1"] # recorded["n1"]
      [] OTHER -> \E n \in Governs : ident[n] # recorded[n]

FlagIsExact == Flag <=> ShouldFlag

\* Reachability.
NeverFlagged == ~Flag
=============================================================================
