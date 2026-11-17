----------------------------- MODULE IntentTree -----------------------------
(***************************************************************************)
(* A parent intent with children (claim C34).                              *)
(*                                                                         *)
(* The root has one criterion of its own and up to two children, each with *)
(* one criterion. The owner confirms the whole shape: which children there *)
(* are and every gate. Adding or removing a child, or editing any gate,    *)
(* makes the root a draft again. The root is delivered only when it is     *)
(* confirmed, the tree has enough hard gates in total, its own hard gate   *)
(* passes, and every child is delivered. A child with no hard gate is      *)
(* never delivered.                                                        *)
(*                                                                         *)
(* Not covered: more than one level of children, exceptions, deferred      *)
(* gates of children.                                                      *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS MinHard, Mutant

VARIABLES present, gate, chk, confirmed, basePresent, baseGate

vars == <<present, gate, chk, confirmed, basePresent, baseGate>>

Kids  == {"k1", "k2"}
Nodes == Kids \cup {"root"}
Gates == {"hard", "soft"}

Mutants == {"none", "remove_keeps_confirmation", "add_keeps_confirmation",
            "delivered_ignores_children", "soft_child_is_delivered"}
ASSUME Mutant \in Mutants /\ MinHard \in Nat

Init ==
    /\ present \in SUBSET Kids
    /\ gate \in [Nodes -> Gates]
    /\ chk = [n \in Nodes |-> "unknown"]
    /\ confirmed = FALSE
    /\ basePresent = present
    /\ baseGate = gate

CheckChange(n, v) ==
    /\ v # chk[n]
    /\ chk' = [chk EXCEPT ![n] = v]
    /\ UNCHANGED <<present, gate, confirmed, basePresent, baseGate>>

Confirm ==
    /\ ~confirmed
    /\ confirmed' = TRUE /\ basePresent' = present /\ baseGate' = gate
    /\ UNCHANGED <<present, gate, chk>>

EditGate(n, g) ==
    /\ g # gate[n]
    /\ gate' = [gate EXCEPT ![n] = g]
    /\ confirmed' = FALSE
    /\ UNCHANGED <<present, chk, basePresent, baseGate>>

RemoveChild(k) ==
    /\ k \in present
    /\ present' = present \ {k}
    /\ confirmed' = IF Mutant = "remove_keeps_confirmation" THEN confirmed ELSE FALSE
    /\ UNCHANGED <<gate, chk, basePresent, baseGate>>

AddChild(k) ==
    /\ k \notin present
    /\ present' = present \cup {k}
    /\ confirmed' = IF Mutant = "add_keeps_confirmation" THEN confirmed ELSE FALSE
    /\ UNCHANGED <<gate, chk, basePresent, baseGate>>

Next ==
    \/ \E n \in Nodes, v \in {"unknown", "passed", "failed"} : CheckChange(n, v)
    \/ Confirm
    \/ \E n \in Nodes, g \in Gates : EditGate(n, g)
    \/ \E k \in Kids : RemoveChild(k) \/ AddChild(k)

Spec == Init /\ [][Next]_vars
----------------------------------------------------------------------------
InTree == present \cup {"root"}
HardTotal == Cardinality({n \in InTree : gate[n] = "hard"})

ChildDelivered(k) ==
    IF gate[k] = "hard" THEN chk[k] = "passed" ELSE Mutant = "soft_child_is_delivered"

ReportDelivered ==
    /\ confirmed
    /\ HardTotal >= MinHard
    /\ gate["root"] = "hard" => chk["root"] = "passed"
    /\ Mutant = "delivered_ignores_children" \/ \A k \in present : ChildDelivered(k)

\* Delivered: every hard gate anywhere in the tree passes, and every child
\* has a hard gate.
TreeSound ==
    ReportDelivered =>
        /\ \A n \in InTree : gate[n] = "hard" => chk[n] = "passed"
        /\ \A k \in present : gate[k] = "hard"

\* While confirmed, the tree is exactly the one the owner confirmed.
ShapeIsConfirmed ==
    confirmed => present = basePresent /\ \A n \in Nodes : gate[n] = baseGate[n]

\* Reachability: expected to be VIOLATED.
NeverDelivered == ~(ReportDelivered /\ present # {})
=============================================================================
