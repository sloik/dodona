------------------------------- MODULE MC -------------------------------
(* Bounded instance of EvidenceReuse for the TLC model checker. *)
EXTENDS EvidenceReuse, TLC

MCTrueDeps      == ("o1" :> {"d1"}) @@ ("o2" :> {"d1", "d2"})
\* o2 really depends on d2 as well; this declaration leaves it out.
MCUnderDeclared == ("o1" :> {"d1"}) @@ ("o2" :> {"d1"})

\* Bound on runs in flight, to keep the state space finite and small.
RunBound == Cardinality(running) <= 2
=========================================================================
