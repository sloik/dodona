--------------------------- MODULE EvidenceReuse ---------------------------
(***************************************************************************)
(* The kernel's evidence-reuse rule (decisions 0005 and 0006).             *)
(*                                                                         *)
(* Definitions and the pinned tool have content hashes that change at any  *)
(* time. An obligation is checked by submitting a run to an execution      *)
(* backend that may be down, and that may lose a run. A completed run      *)
(* leaves a record in an append-only ledger. The kernel reports an         *)
(* obligation as passed or failed only from a ledger record whose          *)
(* evidence key equals the key computed from the current state.            *)
(*                                                                         *)
(* Safety claim: a reported pass is true for the current inputs, and a     *)
(* reported failure is false for them, whatever the interleaving of        *)
(* edits, re-pins, outages, lost runs and completions.                     *)
(*                                                                         *)
(* Mutant selects a planted defect. "none" is the intended design; every   *)
(* other value must make TLC report a violation of Sound.                  *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Defs,           \* definitions
    Obligations,    \* obligations to check
    Hashes,         \* possible content hashes, a finite subset of Nat
    TrueDeps,       \* [Obligations -> SUBSET Defs]: what a result really depends on
    UnderDeclared,  \* [Obligations -> SUBSET Defs]: an incomplete declaration, used by one mutant
    Mutant

VARIABLES
    defHash,    \* [Defs -> Hashes]: current content of each definition
    toolHash,   \* current digest of the pinned tool
    backend,    \* "up" or "down"
    running,    \* runs in flight, each with the key and input snapshot taken at submission
    ledger      \* append-only set of reusable records

vars == <<defHash, toolHash, backend, running, ledger>>

Mutants == {"none", "key_omits_tool", "complete_with_current_key",
            "unavailable_is_pass", "undeclared_dep"}

ASSUME /\ Mutant \in Mutants
       /\ Hashes \subseteq Nat
       /\ TrueDeps \in [Obligations -> SUBSET Defs]
       /\ UnderDeclared \in [Obligations -> SUBSET Defs]

\* The dependencies the provider declared. Sound reuse assumes the declaration
\* is complete (trusted base); the "undeclared_dep" mutant breaks that assumption.
DeclaredDeps(o) == IF Mutant = "undeclared_dep" THEN UnderDeclared[o] ELSE TrueDeps[o]

\* The evidence key for obligation o in the current state.
Key(o) == [ deps |-> [d \in DeclaredDeps(o) |-> defHash[d]],
            tool |-> IF Mutant = "key_omits_tool" THEN 0 ELSE toolHash ]

\* Ground truth: whether obligation o holds for given inputs. Any function that
\* depends on every true dependency and on the tool would do; parity makes each
\* single change flip the answer, so a missed input is always observable.
Holds(o, dh, th) ==
    (Cardinality({d \in TrueDeps[o] : dh[d] % 2 = 1}) + th) % 2 = 0

ReusableVerdicts == {"passed", "failed"}

Reusable(o) == {r \in ledger : r.ob = o /\ r.key = Key(o)}

\* What the kernel reports for o.
Status(o) ==
    IF \E r \in Reusable(o) : r.verdict = "passed" THEN "passed"
    ELSE IF \E r \in Reusable(o) : r.verdict = "failed" THEN "failed"
    ELSE IF \E j \in running : j.ob = o /\ j.key = Key(o) THEN "pending"
    ELSE "unknown"

Init ==
    /\ defHash \in [Defs -> Hashes]
    /\ toolHash \in Hashes
    /\ backend = "up"
    /\ running = {}
    /\ ledger = {}

Edit(d, h) ==
    /\ h # defHash[d]
    /\ defHash' = [defHash EXCEPT ![d] = h]
    /\ UNCHANGED <<toolHash, backend, running, ledger>>

Repin(h) ==
    /\ h # toolHash
    /\ toolHash' = h
    /\ UNCHANGED <<defHash, backend, running, ledger>>

BackendFlip ==
    /\ backend' = IF backend = "up" THEN "down" ELSE "up"
    /\ UNCHANGED <<defHash, toolHash, running, ledger>>

\* Ask for o to be checked. Nothing is submitted when a reusable record or an
\* identical run already exists. With the backend down the outcome is
\* "unavailable", which leaves no reusable record.
Submit(o) ==
    /\ Status(o) = "unknown"
    /\ IF backend = "up"
       THEN /\ running' = running \cup
                  {[ob |-> o, key |-> Key(o),
                    dh |-> [d \in TrueDeps[o] |-> defHash[d]], th |-> toolHash]}
            /\ UNCHANGED ledger
       ELSE /\ ledger' = IF Mutant = "unavailable_is_pass"
                         THEN ledger \cup {[ob |-> o, key |-> Key(o), verdict |-> "passed"]}
                         ELSE ledger
            /\ UNCHANGED running
    /\ UNCHANGED <<defHash, toolHash, backend>>

\* A run finishes. It judged the inputs it was given at submission. The record
\* is filed under the key fixed at submission; the mutant files it under the
\* key computed at completion instead.
Complete(j) ==
    /\ j \in running
    /\ running' = running \ {j}
    /\ LET verdict == IF Holds(j.ob, j.dh, j.th) THEN "passed" ELSE "failed"
           key     == IF Mutant = "complete_with_current_key" THEN Key(j.ob) ELSE j.key
       IN  ledger' = ledger \cup {[ob |-> j.ob, key |-> key, verdict |-> verdict]}
    /\ UNCHANGED <<defHash, toolHash, backend>>

\* A run ends without a result: crash, timeout, cancellation, lost backend.
\* The outcome is "error" or "unavailable", which leaves no reusable record.
Lose(j) ==
    /\ j \in running
    /\ running' = running \ {j}
    /\ UNCHANGED <<defHash, toolHash, backend, ledger>>

Next ==
    \/ \E d \in Defs, h \in Hashes : Edit(d, h)
    \/ \E h \in Hashes : Repin(h)
    \/ BackendFlip
    \/ \E o \in Obligations : Submit(o)
    \/ \E j \in running : Complete(j) \/ Lose(j)

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
TypeOK ==
    /\ defHash \in [Defs -> Hashes]
    /\ toolHash \in Hashes
    /\ backend \in {"up", "down"}
    /\ \A j \in running : j.ob \in Obligations
    /\ \A r \in ledger : r.ob \in Obligations /\ r.verdict \in ReusableVerdicts

\* A reported pass is true now, and a reported failure is false now.
Sound ==
    \A o \in Obligations :
        /\ Status(o) = "passed" => Holds(o, defHash, toolHash)
        /\ Status(o) = "failed" => ~Holds(o, defHash, toolHash)

\* No key ever has both a pass and a failure recorded.
Consistent ==
    \A r1, r2 \in ledger :
        (r1.ob = r2.ob /\ r1.key = r2.key) => r1.verdict = r2.verdict

\* Non-vacuity: these are expected to be VIOLATED in the intended design,
\* showing that a pass, a failure and a reuse after an edit are all reachable.
NeverPassed == \A o \in Obligations : Status(o) # "passed"
NeverFailed == \A o \in Obligations : Status(o) # "failed"
=============================================================================
