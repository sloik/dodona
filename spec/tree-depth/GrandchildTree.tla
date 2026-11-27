--------------------------- MODULE GrandchildTree ---------------------------
(* A rooted tree with a grandchild (claim C34, decision 0030).             *)
(* Fixed chain root -> kid -> grand, one criterion each, hard or soft.     *)
(* Shape never changes; only gates (edits), checks and confirmation do.    *)
(* Decision 0030 as chosen: the floor is counted at the root over its      *)
(* unique descendants; every non-root intent needs a hard gate somewhere   *)
(* in its own subtree. A floor below one counts as one.                    *)
(* SPECIFICATION: confirmation from event order; counts from an            *)
(* independent recursive ancestor relation. KERNEL: one flag cleared on    *)
(* each edit, and running counts per intent updated by propagating to a    *)
(* hand-written ancestor chain. They share only HardPass.                  *)
(* Not covered: add/remove, other topologies, deeper trees, an intent with *)
(* no criteria, exceptions, deferred gates, the coverage display.          *)
EXTENDS Integers, FiniteSets
CONSTANTS MinHard, Mutant
VARIABLES gate, chk, confirmed, events, lastConfirm, lastChange, kcount
vars == <<gate, chk, confirmed, events, lastConfirm, lastChange, kcount>>

Nodes == {"root", "kid", "grand"}
Gates == {"hard", "soft"}
Checks == {"unknown", "passed", "failed"}
MaxEvents == 3
Mutants == {"none", "direct_child_count", "grandchild_edit_keeps_confirmation"}
ASSUME Mutant \in Mutants /\ MinHard \in 0..3
Floor == IF MinHard < 1 THEN 1 ELSE MinHard
Parent == [kid |-> "root", grand |-> "kid"]

(* Specification: recursive, independent of the kernel. *)
RECURSIVE Anc(_)
Anc(n) == IF n = "root" THEN {} ELSE {Parent[n]} \cup Anc(Parent[n])
Subtree(n) == {m \in Nodes : m = n \/ n \in Anc(m)}
SpecCount(n) == Cardinality({m \in Subtree(n) : gate[m] = "hard"})  \* a set: each intent once
SpecGuarded(n) == SpecCount(n) >= (IF n = "root" THEN Floor ELSE 1)
SpecConfirmed == lastConfirm > 0 /\ lastConfirm > lastChange
HardPass(n) == gate[n] = "hard" => chk[n] = "passed"
SpecDelivered == SpecConfirmed /\ \A n \in Nodes : SpecGuarded(n) /\ HardPass(n)

(* Kernel: running counts by propagation, no recursion. The planted defect
   stops one level up, so the root counts only its direct children. *)
Reaches(x, n) ==
    \/ n = x
    \/ x # "root" /\ n = Parent[x]
    \/ Mutant # "direct_child_count" /\ x = "grand" /\ n = "root"
KInit(g) == [n \in Nodes |-> Cardinality({x \in Nodes : Reaches(x, n) /\ g[x] = "hard"})]
KGuarded(n) == kcount[n] >= (IF n = "root" THEN Floor ELSE 1)
KernelDelivered == confirmed /\ \A n \in Nodes : KGuarded(n) /\ HardPass(n)

Init ==
    /\ gate \in [Nodes -> Gates]
    /\ chk = [n \in Nodes |-> "unknown"]
    /\ kcount = KInit(gate)
    /\ confirmed = FALSE
    /\ events = 0 /\ lastConfirm = 0 /\ lastChange = 0
Tick == events < MaxEvents /\ events' = events + 1
CheckChange(n, v) ==
    /\ v # chk[n] /\ chk' = [chk EXCEPT ![n] = v]
    /\ UNCHANGED <<gate, confirmed, events, lastConfirm, lastChange, kcount>>
Confirm ==
    /\ Tick /\ confirmed' = TRUE /\ lastConfirm' = events + 1
    /\ UNCHANGED <<gate, chk, lastChange, kcount>>
EditGate(x, g) ==
    /\ Tick /\ g # gate[x]
    /\ gate' = [gate EXCEPT ![x] = g]
    /\ confirmed' = IF Mutant = "grandchild_edit_keeps_confirmation" /\ x = "grand" THEN confirmed ELSE FALSE
    /\ lastChange' = events + 1
    /\ LET d == IF g = "hard" THEN 1 ELSE -1
       IN kcount' = [n \in Nodes |-> kcount[n] + (IF Reaches(x, n) THEN d ELSE 0)]
    /\ UNCHANGED <<chk, lastConfirm>>
Next ==
    \/ \E n \in Nodes, v \in Checks : CheckChange(n, v)
    \/ Confirm
    \/ \E x \in Nodes, g \in Gates : EditGate(x, g)
Spec == Init /\ [][Next]_vars
----------------------------------------------------------------------------
TypeOK ==
    /\ gate \in [Nodes -> Gates] /\ chk \in [Nodes -> Checks] /\ confirmed \in BOOLEAN
    /\ events \in 0..MaxEvents /\ lastConfirm \in 0..MaxEvents /\ lastChange \in 0..MaxEvents
    /\ kcount \in [Nodes -> 0..3]
ConfirmationMatches == confirmed = SpecConfirmed
DeliveryMatches == KernelDelivered = SpecDelivered
\* Reachability control, expected VIOLATED: the fixture's state after confirm.
NeverDeliveredSoftMiddle ==
    ~(/\ SpecDelivered /\ KernelDelivered
      /\ gate["root"] = "hard" /\ gate["kid"] = "soft" /\ gate["grand"] = "hard")
=============================================================================
