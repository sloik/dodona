---------------------------- MODULE IntentGates ----------------------------
(***************************************************************************)
(* Delivery of one intent (decisions 0018 and 0020).                       *)
(*                                                                         *)
(* An intent has criteria. Each criterion has a gate, declared up front:   *)
(* hard, soft or deferred. The result of the check behind each criterion   *)
(* changes at any time. The gate of a criterion can be changed only by an  *)
(* amendment, granted by the owner of the intent. An amendment granted by  *)
(* the party that did the work is self-granted: it is always marked, and   *)
(* it does not take effect where an independent approver is required.      *)
(*                                                                         *)
(* What this model does NOT cover: child intents, changes to the text of   *)
(* a criterion, assurance levels, time limits on deferred gates, how an    *)
(* identity is established, and checks that vary between runs.             *)
(*                                                                         *)
(* Mutant selects a planted defect; "none" is the intended design.         *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Crits,               \* criteria of the intent
    DeclGate,            \* [Crits -> Gates]: gates declared up front
    SameParty,           \* TRUE when the owner of the intent also does the work
    IndependentApprover, \* TRUE when policy requires an independent approver
    Mutant

VARIABLES
    chk,         \* [Crits -> {"unknown","passed","failed"}]: status of the check behind each criterion
    effGate,     \* [Crits -> Gates]: the gate in force
    amendments   \* every amendment ever granted

vars == <<chk, effGate, amendments>>

Gates   == {"hard", "soft", "deferred"}
Parties == {"owner", "worker"}
Mutants == {"none", "worker_can_amend", "self_counts", "hide_self", "silent_change",
            "delivered_ignores_unknown", "deferred_as_passed"}

ASSUME /\ Mutant \in Mutants
       /\ SameParty \in BOOLEAN
       /\ IndependentApprover \in BOOLEAN
       /\ DeclGate \in [Crits -> Gates]

Init ==
    /\ chk = [c \in Crits |-> "unknown"]
    /\ effGate = DeclGate
    /\ amendments = {}

\* The check behind a criterion finishes, or goes stale after a change.
CheckChange(c, v) ==
    /\ v # chk[c]
    /\ chk' = [chk EXCEPT ![c] = v]
    /\ UNCHANGED <<effGate, amendments>>

\* A party grants an amendment moving criterion c to gate g. Only the owner
\* may. It is self-granted when the grantor did the work. Where an independent
\* approver is required, a self-granted amendment is recorded and has no effect.
Amend(c, g, by) ==
    /\ g # effGate[c]
    /\ by = "owner" \/ Mutant = "worker_can_amend"
    /\ LET self    == (by = "worker") \/ SameParty
           counted == (~(IndependentApprover /\ self)) \/ Mutant = "self_counts"
           shown   == IF Mutant = "hide_self" THEN FALSE ELSE self
       IN  /\ amendments' = amendments \cup
                  {[crit |-> c, to |-> g, by |-> by, self |-> self,
                    counted |-> counted, shown |-> shown]}
           /\ effGate' = IF counted THEN [effGate EXCEPT ![c] = g] ELSE effGate
    /\ UNCHANGED chk

\* Planted defect only: a gate changes with nothing on record.
SilentChange(c, g) ==
    /\ Mutant = "silent_change"
    /\ g # effGate[c]
    /\ effGate' = [effGate EXCEPT ![c] = g]
    /\ UNCHANGED <<chk, amendments>>

Next ==
    \/ \E c \in Crits, v \in {"unknown", "passed", "failed"} : CheckChange(c, v)
    \/ \E c \in Crits, g \in Gates, by \in Parties : Amend(c, g, by)
    \/ \E c \in Crits, g \in Gates : SilentChange(c, g)

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
\* What the kernel reports.

ReportDelivered ==
    \A c \in Crits : effGate[c] = "hard" =>
        IF Mutant = "delivered_ignores_unknown" THEN chk[c] # "failed" ELSE chk[c] = "passed"

ReportFulfilled ==
    /\ ReportDelivered
    /\ Mutant = "deferred_as_passed" \/ \A c \in Crits : effGate[c] = "deferred" => chk[c] = "passed"

----------------------------------------------------------------------------
\* Properties expected to HOLD in the intended design.

TypeOK ==
    /\ chk \in [Crits -> {"unknown", "passed", "failed"}]
    /\ effGate \in [Crits -> Gates]

\* Delivered: every criterion whose gate is hard has a passing check.
DeliveredSound ==
    ReportDelivered => \A c \in Crits : effGate[c] = "hard" => chk[c] = "passed"

\* Fulfilled: every hard and every deferred criterion has a passing check.
FulfilledSound ==
    ReportFulfilled => \A c \in Crits : effGate[c] \in {"hard", "deferred"} => chk[c] = "passed"

\* A gate differs from the declared one only through an amendment on record
\* that took effect.
GateProvenance ==
    \A c \in Crits : effGate[c] # DeclGate[c] =>
        \E a \in amendments : a.crit = c /\ a.to = effGate[c] /\ a.counted

\* Only the owner's amendments take effect.
OnlyOwnerAmends == \A a \in amendments : a.counted => a.by = "owner"

\* Where an independent approver is required, no self-granted amendment takes effect.
NoSelfWhenIndependent ==
    IndependentApprover => \A a \in amendments : a.counted => ~a.self

\* A self-granted amendment is always marked as one.
SelfShown == \A a \in amendments : a.self => a.shown

----------------------------------------------------------------------------
\* Reachability: each is expected to be VIOLATED, showing the behaviour exists.

NeverDelivered == ~ReportDelivered \/ \A c \in Crits : effGate[c] # "hard"
NeverFulfilled == ~(ReportFulfilled /\ \E c \in Crits : effGate[c] = "deferred")
\* Delivered while a criterion declared hard is not passing, by way of an amendment.
NeverDeliveredByAmendment ==
    ~(ReportDelivered /\ \E c \in Crits : DeclGate[c] = "hard" /\ chk[c] # "passed")
=============================================================================
