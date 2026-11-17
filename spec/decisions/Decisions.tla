----------------------------- MODULE Decisions -----------------------------
(***************************************************************************)
(* A decision is flagged when what it governs changes (claim C16).         *)
(*                                                                         *)
(* Two named definitions. Each name has a content identity, or is gone     *)
(* (identity 0). A decision governs the name n1 and records the identity   *)
(* n1 had when the decision was written or last reviewed. It must be       *)
(* flagged exactly when the identity behind n1 is no longer that one.      *)
(*                                                                         *)
(* In a language that addresses code by content, an edit is a new identity *)
(* behind an old name. A kernel that tracks identities without names       *)
(* cannot tell that from a deletion, and misses the case where the old     *)
(* content still exists under another name.                                *)
(***************************************************************************)
EXTENDS Naturals

CONSTANT Mutant

VARIABLES ident, recorded

vars == <<ident, recorded>>

Names == {"n1", "n2"}
Idents == {0, 1, 2}

Mutants == {"none", "identities_without_names", "gone_is_not_flagged"}
ASSUME Mutant \in Mutants

Init == ident \in [Names -> {1, 2}] /\ recorded = ident["n1"]

Edit(n, h) == h # ident[n] /\ ident' = [ident EXCEPT ![n] = h] /\ UNCHANGED recorded

\* The decision is reviewed against what n1 is now.
Review == ident["n1"] # 0 /\ recorded # ident["n1"] /\ recorded' = ident["n1"] /\ UNCHANGED ident

Next == (\E n \in Names, h \in Idents : Edit(n, h)) \/ Review

Spec == Init /\ [][Next]_vars
----------------------------------------------------------------------------
ShouldFlag == ident["n1"] # recorded

Flag ==
    CASE Mutant = "identities_without_names" -> ~\E n \in Names : ident[n] = recorded
      [] Mutant = "gone_is_not_flagged" -> ident["n1"] # recorded /\ ident["n1"] # 0
      [] OTHER -> ident["n1"] # recorded

FlagIsExact == Flag <=> ShouldFlag

\* Reachability.
NeverFlagged == ~Flag
=============================================================================
