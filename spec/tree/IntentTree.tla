----------------------------- MODULE IntentTree -----------------------------
(***************************************************************************)
(* A parent intent with a child (claim C34, decision 0017).                *)
(*                                                                         *)
(* The root and the child each have two criteria, each hard or soft. The   *)
(* child may be in the tree or not. The owner confirms the whole shape:    *)
(* whether the child is there and every gate. Adding or removing the       *)
(* child, or editing any gate, makes the tree a draft until it is          *)
(* confirmed again. The tree is delivered when it is confirmed, every      *)
(* intent in it is guarded, and every hard gate passes (decision 0030). An *)
(* intent's hard gates are counted over it and its descendants. The root   *)
(* must count at least what policy demands; moving a criterion into a      *)
(* child changes nothing in that count (decision 0017). Every intent in    *)
(* the tree, the child too, must count at least one hard gate.             *)
(*                                                                         *)
(* Two descriptions are kept apart on purpose. The SPECIFICATION decides   *)
(* confirmation from the order of events: the last confirmation came after *)
(* the last change of shape, and counts gates from the tree as it is. The  *)
(* KERNEL keeps one flag and clears it on each change, and keeps a running *)
(* count of hard gates per intent, updated on each change, as an index     *)
(* does. Both share HardPass, so whether every hard gate passes is a       *)
(* restated rule; confirmation and counting are not. The properties say    *)
(* the kernel reports confirmation and delivery exactly as the             *)
(* specification calls for them.                                           *)
(*                                                                         *)
(* Not covered: more than one child or level, exceptions, deferred gates.  *)
(***************************************************************************)
EXTENDS Integers, FiniteSets

CONSTANTS MinHard, Mutant

VARIABLES present, gate, chk, confirmed, events, lastConfirm, lastChange, kcount

vars == <<present, gate, chk, confirmed, events, lastConfirm, lastChange, kcount>>

Nodes == {"root", "kid"}
Crits == {"a", "b"}
Gates == {"hard", "soft"}
MaxEvents == 6

Mutants == {"none", "remove_keeps_confirmation", "add_keeps_confirmation", "edit_keeps_confirmation",
            "unconfirmed_delivered", "delivered_ignores_child", "soft_child_is_delivered",
            "ignores_floor", "floor_applied_to_each_child", "floor_counts_root_only", "count_kept_on_remove",
            "count_misses_child_edit"}
ASSUME Mutant \in Mutants /\ MinHard \in 1..2

Own(g, n) == Cardinality({c \in Crits : g[<<n, c>>] = "hard"})

Init ==
    /\ present \in BOOLEAN
    /\ gate \in [Nodes \X Crits -> Gates]
    /\ kcount = [root |-> Own(gate, "root") + (IF present THEN Own(gate, "kid") ELSE 0), kid |-> Own(gate, "kid")]
    /\ chk = [x \in Nodes \X Crits |-> "unknown"]
    /\ confirmed = FALSE
    /\ events = 0 /\ lastConfirm = 0 /\ lastChange = 0

\* The events the specification orders. Checks are not changes of shape.
Tick == events < MaxEvents /\ events' = events + 1

CheckChange(x, v) ==
    /\ v # chk[x]
    /\ chk' = [chk EXCEPT ![x] = v]
    /\ UNCHANGED <<present, gate, confirmed, events, lastConfirm, lastChange, kcount>>

Confirm ==
    /\ Tick
    /\ confirmed' = TRUE /\ lastConfirm' = events + 1
    /\ UNCHANGED <<present, gate, chk, lastChange, kcount>>

\* A gate of the child can be edited only while the child is in the tree.
EditGate(x, g) ==
    /\ Tick
    /\ g # gate[x]
    /\ x[1] = "kid" => present
    /\ gate' = [gate EXCEPT ![x] = g]
    /\ confirmed' = IF Mutant = "edit_keeps_confirmation" THEN confirmed ELSE FALSE
    /\ lastChange' = events + 1
    /\ LET d == IF g = "hard" THEN 1 ELSE -1
       IN kcount' = IF x[1] = "root" THEN [kcount EXCEPT !.root = @ + d]
                    ELSE IF Mutant = "count_misses_child_edit" THEN [kcount EXCEPT !.kid = @ + d]
                    ELSE [kcount EXCEPT !.root = @ + d, !.kid = @ + d]
    /\ UNCHANGED <<present, chk, lastConfirm>>

Toggle ==
    /\ Tick
    /\ present' = ~present
    /\ chk' = IF present THEN chk ELSE [x \in Nodes \X Crits |-> IF x[1] = "kid" THEN "unknown" ELSE chk[x]]
    /\ confirmed' = IF (present /\ Mutant = "remove_keeps_confirmation") \/ (~present /\ Mutant = "add_keeps_confirmation")
                    THEN confirmed ELSE FALSE
    /\ lastChange' = events + 1
    /\ kcount' = IF present
                 THEN (IF Mutant = "count_kept_on_remove" THEN kcount ELSE [kcount EXCEPT !.root = @ - kcount.kid])
                 ELSE [kcount EXCEPT !.root = @ + kcount.kid]
    /\ UNCHANGED <<gate, lastConfirm>>

Next ==
    \/ \E x \in Nodes \X Crits, v \in {"unknown", "passed", "failed"} : CheckChange(x, v)
    \/ Confirm
    \/ \E x \in Nodes \X Crits, g \in Gates : EditGate(x, g)
    \/ Toggle

Spec == Init /\ [][Next]_vars
----------------------------------------------------------------------------
InTree == IF present THEN Nodes ELSE {"root"}
HardOf(n) == Own(gate, n)
HardPass(n) == \A c \in Crits : gate[<<n, c>>] = "hard" => chk[<<n, c>>] = "passed"

(* The specification. *)
SpecConfirmed == lastConfirm > 0 /\ lastConfirm > lastChange
\* An intent's count is over it and its descendants.
SpecCount(n) == IF n = "root" THEN HardOf("root") + (IF present THEN HardOf("kid") ELSE 0) ELSE HardOf("kid")
SpecGuarded(n) == SpecCount(n) >= (IF n = "root" THEN MinHard ELSE 1)
SpecDelivered ==
    /\ SpecConfirmed
    /\ \A n \in InTree : SpecGuarded(n) /\ HardPass(n)

(* The kernel. *)
Guarded(n) ==
    CASE Mutant = "ignores_floor" -> TRUE
      [] Mutant = "floor_applied_to_each_child" -> kcount[n] >= MinHard
      [] Mutant = "floor_counts_root_only" -> (IF n = "root" THEN kcount.root - (IF present THEN kcount.kid ELSE 0) ELSE kcount.kid) >= MinHard
      [] OTHER -> kcount[n] >= (IF n = "root" THEN MinHard ELSE 1)
ChildOK ==
    CASE Mutant = "delivered_ignores_child" -> TRUE
      [] Mutant = "soft_child_is_delivered" -> HardOf("kid") = 0 \/ (Guarded("kid") /\ HardPass("kid"))
      [] OTHER -> Guarded("kid") /\ HardPass("kid")
KernelDelivered ==
    /\ confirmed \/ Mutant = "unconfirmed_delivered"
    /\ Guarded("root") /\ HardPass("root")
    /\ present => ChildOK
----------------------------------------------------------------------------
TypeOK ==
    /\ present \in BOOLEAN
    /\ gate \in [Nodes \X Crits -> Gates]
    /\ chk \in [Nodes \X Crits -> {"unknown", "passed", "failed"}]
    /\ confirmed \in BOOLEAN
    /\ events \in 0..MaxEvents /\ lastConfirm \in 0..MaxEvents /\ lastChange \in 0..MaxEvents
    /\ kcount \in [{"root", "kid"} -> -4..8]

\* The kernel's confirmation is the one the order of events calls for.
ConfirmationMatches == confirmed = SpecConfirmed

\* The kernel reports delivery exactly when the specification calls for it: never for a draft,
\* never below the floor anywhere in the tree, never with a hard gate unpassed, and always
\* when all of that holds.
DeliveryMatches == KernelDelivered = SpecDelivered

\* Reachability: expected to be VIOLATED.
NeverDelivered == ~(SpecDelivered /\ present)
=============================================================================
