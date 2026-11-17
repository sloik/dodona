------------------------------ MODULE MCDump ------------------------------
(* The evidence-reuse model with the kernel's answer written into every    *)
(* state, so that the model checker's list of reachable states can be used *)
(* to judge an implementation: `report` is what the model says the status  *)
(* of each obligation is in that state.                                    *)
EXTENDS MC

VARIABLE report

DumpInit == Init /\ report = [o \in Obligations |-> Status(o)]
DumpNext == Next /\ report' = [o \in Obligations |-> Status(o)']
DumpSpec == DumpInit /\ [][DumpNext]_<<vars, report>>

\* One run in flight and at most three records keep the list of states small
\* enough to move: tens of thousands of states instead of millions. Both
\* obligations and their shared dependency are still there.
DumpBound == Cardinality(running) <= 1 /\ Cardinality(ledger) <= 3
=============================================================================
