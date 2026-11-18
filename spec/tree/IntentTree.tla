----------------------------- MODULE IntentTree -----------------------------
(***************************************************************************)
(* A parent intent with a child (claim C34, decision 0017).                *)
(*                                                                         *)
(* The root and the child each have two criteria, each hard or soft. The   *)
(* child may be in the tree or not. The owner confirms the whole shape:    *)
(* whether the child is there and every gate. Adding or removing the       *)
(* child, or editing any gate, makes the tree a draft until it is          *)
(* confirmed again. The tree is delivered when it is confirmed, every      *)
(* intent in it, the child as well as the root, has at least the hard      *)
(* gates policy demands, and every hard gate passes. A child is an intent: *)
(* the floor applies to it as it does to the root.                         *)
(*                                                                         *)
(* Two descriptions are kept apart on purpose. The SPECIFICATION decides   *)
(* confirmation from the order of events: the last confirmation came after *)
(* the last change of shape. The KERNEL keeps one flag and clears it on    *)
(* each change, as a real kernel does. The properties say the kernel       *)
(* reports delivery exactly when the specification calls for it. A kernel *)
(* that keeps the flag across a change, or decides delivery by the wrong   *)
(* rule, is caught.                                                        *)
(*                                                                         *)
(* Not covered: more than one child or level, exceptions, deferred gates.  *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS MinHard, Mutant

VARIABLES present, gate, chk, confirmed, events, lastConfirm, lastChange

vars == <<present, gate, chk, confirmed, events, lastConfirm, lastChange>>

Nodes == {"root", "kid"}
Crits == {"a", "b"}
Gates == {"hard", "soft"}
MaxEvents == 6

Mutants == {"none", "remove_keeps_confirmation", "add_keeps_confirmation", "edit_keeps_confirmation",
            "unconfirmed_delivered", "delivered_ignores_child", "soft_child_is_delivered",
            "ignores_floor", "floor_counts_tree", "floor_counts_root_only"}
ASSUME Mutant \in Mutants /\ MinHard \in 1..2

Init ==
    /\ present \in BOOLEAN
    /\ gate \in [Nodes \X Crits -> Gates]
    /\ chk = [x \in Nodes \X Crits |-> "unknown"]
    /\ confirmed = FALSE
    /\ events = 0 /\ lastConfirm = 0 /\ lastChange = 0

\* The events the specification orders. Checks are not changes of shape.
Tick == events < MaxEvents /\ events' = events + 1

CheckChange(x, v) ==
    /\ v # chk[x]
    /\ chk' = [chk EXCEPT ![x] = v]
    /\ UNCHANGED <<present, gate, confirmed, events, lastConfirm, lastChange>>

Confirm ==
    /\ Tick
    /\ confirmed' = TRUE /\ lastConfirm' = events + 1
    /\ UNCHANGED <<present, gate, chk, lastChange>>

EditGate(x, g) ==
    /\ Tick
    /\ g # gate[x]
    /\ gate' = [gate EXCEPT ![x] = g]
    /\ confirmed' = IF Mutant = "edit_keeps_confirmation" THEN confirmed ELSE FALSE
    /\ lastChange' = events + 1
    /\ UNCHANGED <<present, chk, lastConfirm>>

Toggle ==
    /\ Tick
    /\ present' = ~present
    /\ confirmed' = IF (present /\ Mutant = "remove_keeps_confirmation") \/ (~present /\ Mutant = "add_keeps_confirmation")
                    THEN confirmed ELSE FALSE
    /\ lastChange' = events + 1
    /\ UNCHANGED <<gate, chk, lastConfirm>>

Next ==
    \/ \E x \in Nodes \X Crits, v \in {"unknown", "passed", "failed"} : CheckChange(x, v)
    \/ Confirm
    \/ \E x \in Nodes \X Crits, g \in Gates : EditGate(x, g)
    \/ Toggle

Spec == Init /\ [][Next]_vars
----------------------------------------------------------------------------
InTree == IF present THEN Nodes ELSE {"root"}
HardOf(n) == Cardinality({c \in Crits : gate[<<n, c>>] = "hard"})
HardPass(n) == \A c \in Crits : gate[<<n, c>>] = "hard" => chk[<<n, c>>] = "passed"

(* The specification. *)
SpecConfirmed == lastConfirm > 0 /\ lastConfirm > lastChange
SpecDelivered ==
    /\ SpecConfirmed
    /\ \A n \in InTree : HardOf(n) >= MinHard /\ HardPass(n)

(* The kernel. *)
Guarded(n) ==
    CASE Mutant = "ignores_floor" -> TRUE
      [] Mutant = "floor_counts_tree" -> HardOf("root") + (IF present THEN HardOf("kid") ELSE 0) >= MinHard
      [] Mutant = "floor_counts_root_only" -> HardOf("root") >= MinHard
      [] OTHER -> HardOf(n) >= MinHard
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

\* The kernel's confirmation is the one the order of events calls for.
ConfirmationMatches == confirmed = SpecConfirmed

\* The kernel reports delivery exactly when the specification calls for it: never for a draft,
\* never below the floor anywhere in the tree, never with a hard gate unpassed, and always
\* when all of that holds.
DeliveryMatches == KernelDelivered = SpecDelivered

\* Reachability: expected to be VIOLATED.
NeverDelivered == ~(SpecDelivered /\ present)
=============================================================================
