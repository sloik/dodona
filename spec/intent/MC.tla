------------------------------- MODULE MC -------------------------------
(* Bounded instances of IntentGates for the TLC model checker. *)
EXTENDS IntentGates, TLC

\* Two hard criteria and one that can only be checked after delivery.
MCThree == ("c1" :> "hard") @@ ("c2" :> "hard") @@ ("c3" :> "deferred")
\* One hard criterion and one deferred.
MCTwo   == ("c1" :> "hard") @@ ("c2" :> "deferred")

\* Bounds on amendments granted. States beyond them are not explored.
AmendBound1 == Cardinality(amendments) <= 1
AmendBound2 == Cardinality(amendments) <= 2
=========================================================================
