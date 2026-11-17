------------------------------- MODULE MC -------------------------------
(* Bounded instance of IntentGates for the TLC model checker. *)
EXTENDS IntentGates, TLC

\* Two hard criteria and one that can only be checked after delivery.
MCDeclGate == ("c1" :> "hard") @@ ("c2" :> "hard") @@ ("c3" :> "deferred")

\* Bound on amendments granted. States beyond it are not explored.
AmendBound == Cardinality(amendments) <= 2
=========================================================================
