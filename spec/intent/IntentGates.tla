---------------------------- MODULE IntentGates ----------------------------
(***************************************************************************)
(* Delivery of one intent (decisions 0017, 0018, 0020 and 0024).           *)
(*                                                                         *)
(* An intent has criteria, each with a gate: hard, soft or deferred. The   *)
(* owner confirms the gates; the confirmed gates are the baseline. The     *)
(* gates can then change in two ways. An edit changes them directly and    *)
(* makes the intent a draft again until the owner confirms. An amendment   *)
(* is an exception granted on the record; it takes effect only if the      *)
(* owner granted it and the grantor was separate enough from the work,     *)
(* as policy demands. How separate a grantor was is a level. When nothing  *)
(* is recorded the level is the lowest one, the worker granting to itself  *)
(* is always the lowest one, and a level that is only declared, not        *)
(* attested, counts as "helper" at most.                                   *)
(*                                                                         *)
(* What this model does NOT cover: child intents, the text of criteria,    *)
(* assurance levels, time limits, checks that vary between runs, and       *)
(* whether a recorded separation level is true. The model takes the        *)
(* recorded level as given; it checks only what the kernel does with it.   *)
(*                                                                         *)
(* Mutant selects a planted defect; "none" is the intended design.         *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Crits,     \* criteria of the intent
    DeclGate,  \* [Crits -> Gates]: gates as first written
    MinSep,    \* policy: least separation at which an exception takes effect
    MaxSep,    \* the most separation a grantor in this scenario can record
    MinHard,   \* policy: least number of hard gates for an intent to be deliverable
    Mutant

VARIABLES
    chk,         \* [Crits -> {"unknown","passed","failed"}]: the check behind each criterion
    effGate,     \* [Crits -> Gates]: the gate in force
    base,        \* [Crits -> Gates]: the gates the owner last confirmed
    confirmed,   \* TRUE when the owner has confirmed and nothing was edited since
    amendments   \* every amendment ever granted

vars == <<chk, effGate, base, confirmed, amendments>>

Gates   == {"hard", "soft", "deferred"}
Parties == {"owner", "worker"}
Levels  == {"self", "helper", "apart"}
Rank(l) == CASE l = "self" -> 0 [] l = "helper" -> 1 [] l = "apart" -> 2

Sources == {"declared", "attested"}

Mutants == {"none", "worker_can_amend", "worker_keeps_level", "below_floor_counts", "missing_is_apart",
            "declared_counts_in_full",
            "hide_level", "edit_keeps_confirmation", "draft_delivers",
            "unguarded_delivers", "delivered_ignores_unknown", "deferred_as_passed"}

ASSUME /\ Mutant \in Mutants
       /\ MinSep \in Levels /\ MaxSep \in Levels
       /\ MinHard \in Nat
       /\ DeclGate \in [Crits -> Gates]

Init ==
    /\ chk = [c \in Crits |-> "unknown"]
    /\ effGate = DeclGate
    /\ base = DeclGate
    /\ confirmed = FALSE
    /\ amendments = {}

\* The check behind a criterion finishes, or goes stale after a change.
CheckChange(c, v) ==
    /\ v # chk[c]
    /\ chk' = [chk EXCEPT ![c] = v]
    /\ UNCHANGED <<effGate, base, confirmed, amendments>>

\* The owner confirms the gates as they stand. They become the baseline.
Confirm ==
    /\ ~confirmed
    /\ confirmed' = TRUE
    /\ base' = effGate
    /\ UNCHANGED <<chk, effGate, amendments>>

\* Anyone edits a gate directly. The intent is a draft again.
Edit(c, g) ==
    /\ g # effGate[c]
    /\ effGate' = [effGate EXCEPT ![c] = g]
    /\ confirmed' = IF Mutant = "edit_keeps_confirmation" THEN confirmed ELSE FALSE
    /\ UNCHANGED <<chk, base, amendments>>

\* A party asks for an exception moving criterion c to gate g, with a recorded
\* separation level, or with none recorded ("missing"). Anyone may ask and the
\* request goes on record. It takes effect only if the owner granted it, at or
\* above the floor. The worker granting to itself is graded "self" whatever
\* level it wrote down. A level that rests only on someone's word is capped at
\* "helper", however high the claim; an attested one stands.
Amend(c, g, by, recorded, src) ==
    /\ confirmed
    /\ g # effGate[c]
    /\ LET level   == IF by = "worker" /\ Mutant # "worker_keeps_level" THEN "self"
                      ELSE IF recorded = "missing"
                           THEN (IF Mutant = "missing_is_apart" THEN "apart" ELSE "self")
                      ELSE IF src = "declared" /\ Mutant # "declared_counts_in_full"
                                /\ Rank(recorded) > Rank("helper")
                           THEN "helper"
                      ELSE recorded
           counted == /\ by = "owner" \/ Mutant = "worker_can_amend"
                      /\ Rank(level) >= Rank(MinSep) \/ Mutant = "below_floor_counts"
           shown   == IF Mutant = "hide_level" THEN "apart" ELSE level
       IN  /\ amendments' = amendments \cup
                  {[crit |-> c, to |-> g, by |-> by, recorded |-> recorded, source |-> src,
                    level |-> level, shown |-> shown, counted |-> counted]}
           /\ effGate' = IF counted THEN [effGate EXCEPT ![c] = g] ELSE effGate
    /\ UNCHANGED <<chk, base, confirmed>>

Recordable == {l \in Levels : Rank(l) <= Rank(MaxSep)} \cup {"missing"}

Next ==
    \/ \E c \in Crits, v \in {"unknown", "passed", "failed"} : CheckChange(c, v)
    \/ Confirm
    \/ \E c \in Crits, g \in Gates : Edit(c, g)
    \/ \E c \in Crits, g \in Gates, by \in Parties, r \in Recordable, src \in Sources :
           Amend(c, g, by, r, src)

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
\* What the kernel reports.

HardCount == Cardinality({c \in Crits : effGate[c] = "hard"})

ReportDelivered ==
    /\ confirmed \/ Mutant = "draft_delivers"
    /\ HardCount >= MinHard \/ Mutant = "unguarded_delivers"
    /\ \A c \in Crits : effGate[c] = "hard" =>
          IF Mutant = "delivered_ignores_unknown" THEN chk[c] # "failed" ELSE chk[c] = "passed"

ReportFulfilled ==
    /\ ReportDelivered
    /\ Mutant = "deferred_as_passed" \/ \A c \in Crits : effGate[c] = "deferred" => chk[c] = "passed"

----------------------------------------------------------------------------
\* Properties expected to HOLD in the intended design.

TypeOK ==
    /\ chk \in [Crits -> {"unknown", "passed", "failed"}]
    /\ effGate \in [Crits -> Gates]
    /\ base \in [Crits -> Gates]
    /\ confirmed \in BOOLEAN

\* Delivered: confirmed by the owner, enough hard gates, every one of them passing.
DeliveredSound ==
    ReportDelivered => \A c \in Crits : effGate[c] = "hard" => chk[c] = "passed"
DeliveredConfirmed == ReportDelivered => confirmed
DeliveredGuarded   == ReportDelivered => HardCount >= MinHard

\* Fulfilled: every hard and every deferred criterion has a passing check.
FulfilledSound ==
    ReportFulfilled => \A c \in Crits : effGate[c] \in {"hard", "deferred"} => chk[c] = "passed"

\* While confirmed, a gate differs from the baseline only through an
\* amendment on record that took effect.
GateProvenance ==
    confirmed => \A c \in Crits : effGate[c] # base[c] =>
        \E a \in amendments : a.crit = c /\ a.to = effGate[c] /\ a.counted

\* Only the owner's amendments take effect, and only at or above the floor.
OnlyOwnerAmends == \A a \in amendments : a.counted => a.by = "owner"
FloorHolds      == \A a \in amendments : a.counted => Rank(a.level) >= Rank(MinSep)

\* Nothing recorded means the lowest level, and so does the worker granting.
DefaultIsLowest == \A a \in amendments : a.recorded = "missing" => a.level = "self"
WorkerIsSelf    == \A a \in amendments : a.by = "worker" => a.level = "self"

\* A claim that rests only on declaration is never graded above "helper".
DeclaredIsCapped ==
    \A a \in amendments : a.source = "declared" => Rank(a.level) <= Rank("helper")

\* The level reported is the level used.
LevelShown == \A a \in amendments : a.shown = a.level

----------------------------------------------------------------------------
\* Reachability: each is expected to be VIOLATED, showing the behaviour exists.

NeverDelivered == ~ReportDelivered
NeverFulfilled == ~(ReportFulfilled /\ \E c \in Crits : effGate[c] = "deferred")
\* Delivered while a criterion the owner confirmed as hard is not passing:
\* possible only by way of an amendment that took effect.
NeverDeliveredByAmendment ==
    ~(ReportDelivered /\ \E c \in Crits : base[c] = "hard" /\ chk[c] # "passed")
=============================================================================
