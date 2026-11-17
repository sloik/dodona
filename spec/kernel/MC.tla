------------------------------- MODULE MC -------------------------------
(* Bounded instances of EvidenceReuse for the TLC model checker. *)
EXTENDS EvidenceReuse, TLC

\* Main instance: two definitions, two obligations, one shared dependency.
MCTrueDeps      == ("o1" :> {"d1"}) @@ ("o2" :> {"d1", "d2"})
\* o2 really depends on d2 as well; this declaration leaves it out.
MCUnderDeclared == ("o1" :> {"d1"}) @@ ("o2" :> {"d1"})

\* Small instance, used where a flaky provider multiplies the ledger states.
MCSmallDeps     == ("o1" :> {"d1"})

\* Bound on runs in flight. States beyond it are not explored.
RunBound == Cardinality(running) <= 2
=========================================================================
