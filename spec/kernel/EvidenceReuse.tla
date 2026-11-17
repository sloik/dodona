--------------------------- MODULE EvidenceReuse ---------------------------
(***************************************************************************)
(* The kernel's evidence-reuse rule (decisions 0005 and 0006).             *)
(*                                                                         *)
(* Definitions and the pinned tool have content hashes that change at any  *)
(* time. An obligation is checked by submitting a run to an execution      *)
(* backend that may be down, and that may lose a run. A completed run      *)
(* leaves a record in the ledger. The kernel derives an obligation's       *)
(* status only from records whose evidence key equals the key computed     *)
(* from the current state.                                                 *)
(*                                                                         *)
(* What this model does NOT cover: more than one kernel, a ledger that     *)
(* loses or alters records, hash collisions, dependency sets that change,  *)
(* platforms, and configuration. Hashes are abstract values, and the       *)
(* model is checked only for the small bounds in MC.tla.                   *)
(*                                                                         *)
(* Mutant selects a planted defect; "none" is the intended design.         *)
(* Flaky = TRUE lets a completed run report the wrong verdict, which       *)
(* breaks the trusted-base assumption that a provider's verdict is         *)
(* correct for its inputs.                                                 *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Defs,           \* definitions
    Obligations,    \* obligations to check
    Hashes,         \* possible content hashes, a finite set of naturals
    TrueDeps,       \* [Obligations -> SUBSET Defs]: what a result really depends on
    UnderDeclared,  \* [Obligations -> SUBSET Defs]: an incomplete declaration, used by one mutant
    Mutant,
    Flaky

VARIABLES
    defHash,    \* [Defs -> Hashes]: current content of each definition
    toolHash,   \* current digest of the pinned tool
    backend,    \* "up" or "down"
    running,    \* runs in flight, each with the key and input snapshot taken at submission
    ledger,     \* set of reusable records
    completed,  \* history: every record produced by a run that completed
    changed     \* history: obligations with a record written before the latest change

vars == <<defHash, toolHash, backend, running, ledger, completed, changed>>

Mutants == {"none", "key_omits_tool", "complete_with_current_key",
            "unavailable_is_pass", "undeclared_dep", "pass_outranks_fail"}

ASSUME /\ Mutant \in Mutants
       /\ Flaky \in BOOLEAN
       /\ \A h \in Hashes : h \in Nat
       /\ TrueDeps \in [Obligations -> SUBSET Defs]
       /\ UnderDeclared \in [Obligations -> SUBSET Defs]

\* The dependencies the provider declared. Sound reuse assumes the declaration
\* is complete (trusted base); the "undeclared_dep" mutant breaks that assumption.
DeclaredDeps(o) == IF Mutant = "undeclared_dep" THEN UnderDeclared[o] ELSE TrueDeps[o]

\* The evidence key for obligation o in the current state.
Key(o) == [ deps |-> [d \in DeclaredDeps(o) |-> defHash[d]],
            tool |-> IF Mutant = "key_omits_tool" THEN 0 ELSE toolHash ]

\* Ground truth: whether obligation o holds for given inputs. Parity makes each
\* single change flip the answer, so a missed input is always observable.
Holds(o, dh, th) ==
    (Cardinality({d \in TrueDeps[o] : dh[d] % 2 = 1}) + th) % 2 = 0

Reusable(o) == {r \in ledger : r.ob = o /\ r.key = Key(o)}

HasPass(o) == \E r \in Reusable(o) : r.verdict = "passed"
HasFail(o) == \E r \in Reusable(o) : r.verdict = "failed"

\* What the kernel reports for o. A key holding both verdicts is a conflict and
\* is not a pass; the mutant lets the pass win.
Status(o) ==
    IF HasPass(o) /\ HasFail(o)
        THEN IF Mutant = "pass_outranks_fail" THEN "passed" ELSE "conflict"
    ELSE IF HasPass(o) THEN "passed"
    ELSE IF HasFail(o) THEN "failed"
    ELSE IF \E j \in running : j.ob = o /\ j.key = Key(o) THEN "pending"
    ELSE "unknown"

HasRecord(o) == \E r \in ledger : r.ob = o

Init ==
    /\ defHash \in [Defs -> Hashes]
    /\ toolHash \in Hashes
    /\ backend = "up"
    /\ running = {}
    /\ ledger = {}
    /\ completed = {}
    /\ changed = {}

Edit(d, h) ==
    /\ h # defHash[d]
    /\ defHash' = [defHash EXCEPT ![d] = h]
    /\ changed' = {o \in Obligations : HasRecord(o)}
    /\ UNCHANGED <<toolHash, backend, running, ledger, completed>>

Repin(h) ==
    /\ h # toolHash
    /\ toolHash' = h
    /\ changed' = {o \in Obligations : HasRecord(o)}
    /\ UNCHANGED <<defHash, backend, running, ledger, completed>>

BackendFlip ==
    /\ backend' = IF backend = "up" THEN "down" ELSE "up"
    /\ UNCHANGED <<defHash, toolHash, running, ledger, completed, changed>>

\* Ask for o to be checked. Normally nothing is submitted when a reusable
\* record exists; with a flaky provider a recheck is always allowed, which is
\* how conflicting records arise. With the backend down the outcome is
\* "unavailable", which leaves no reusable record.
Submit(o) ==
    /\ Status(o) = "unknown" \/ (Flaky /\ Status(o) # "pending")
    /\ IF backend = "up"
       THEN /\ running' = running \cup
                  {[ob |-> o, key |-> Key(o),
                    dh |-> [d \in TrueDeps[o] |-> defHash[d]], th |-> toolHash]}
            /\ UNCHANGED ledger
       ELSE /\ ledger' = IF Mutant = "unavailable_is_pass"
                         THEN ledger \cup {[ob |-> o, key |-> Key(o), verdict |-> "passed"]}
                         ELSE ledger
            /\ UNCHANGED running
    /\ UNCHANGED <<defHash, toolHash, backend, completed, changed>>

\* A run finishes. It judged the inputs it was given at submission. The record
\* is filed under the key fixed at submission; the mutant files it under the
\* key computed at completion instead.
Complete(j) ==
    /\ j \in running
    /\ running' = running \ {j}
    /\ \E right \in (IF Flaky THEN BOOLEAN ELSE {TRUE}) :
         LET truth   == Holds(j.ob, j.dh, j.th)
             verdict == IF truth = right THEN "passed" ELSE "failed"
             key     == IF Mutant = "complete_with_current_key" THEN Key(j.ob) ELSE j.key
             rec     == [ob |-> j.ob, key |-> key, verdict |-> verdict]
         IN  /\ ledger' = ledger \cup {rec}
             /\ completed' = completed \cup {rec}
    /\ changed' = changed \ {j.ob}
    /\ UNCHANGED <<defHash, toolHash, backend>>

\* A run ends without a result: crash, timeout, cancellation, lost backend.
\* The outcome is "error" or "unavailable", which leaves no reusable record.
Lose(j) ==
    /\ j \in running
    /\ running' = running \ {j}
    /\ UNCHANGED <<defHash, toolHash, backend, ledger, completed, changed>>

Next ==
    \/ \E d \in Defs, h \in Hashes : Edit(d, h)
    \/ \E h \in Hashes : Repin(h)
    \/ BackendFlip
    \/ \E o \in Obligations : Submit(o)
    \/ \E j \in running : Complete(j) \/ Lose(j)

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
\* Properties expected to HOLD in the intended design.

TypeOK ==
    /\ defHash \in [Defs -> Hashes]
    /\ toolHash \in Hashes
    /\ backend \in {"up", "down"}
    /\ \A j \in running : j.ob \in Obligations
    /\ \A r \in ledger : r.ob \in Obligations /\ r.verdict \in {"passed", "failed"}
    /\ changed \subseteq Obligations

\* A reported pass: the obligation holds for the current inputs.
\* A reported failure: the obligation does not hold for the current inputs.
Sound ==
    \A o \in Obligations :
        /\ Status(o) = "passed" => Holds(o, defHash, toolHash)
        /\ Status(o) = "failed" => ~Holds(o, defHash, toolHash)

\* Every reusable record was produced by a run that completed.
Provenance == ledger \subseteq completed

\* No key ever has both a pass and a failure recorded.
Consistent ==
    \A r1, r2 \in ledger :
        (r1.ob = r2.ob /\ r1.key = r2.key) => r1.verdict = r2.verdict

\* A pass is never reported while a failure is recorded for the same key.
NoPassOverFail == \A o \in Obligations : Status(o) = "passed" => ~HasFail(o)

----------------------------------------------------------------------------
\* Reachability: each is expected to be VIOLATED, showing the behaviour exists.

NeverPassed   == \A o \in Obligations : Status(o) # "passed"
NeverFailed   == \A o \in Obligations : Status(o) # "failed"
NeverConflict == \A o \in Obligations : Status(o) # "conflict"
\* A record is still used after something changed since it was written:
\* an unrelated edit, or an edit that was later reverted.
NeverReusedAfterChange ==
    \A o \in Obligations : Status(o) \in {"passed", "failed"} => o \notin changed
=============================================================================
