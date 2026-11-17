------------------------------ MODULE Planner ------------------------------
(***************************************************************************)
(* What the planner reruns (claims C8, C9 and C10).                        *)
(*                                                                         *)
(* Three definitions: d1 depends on d2; d3 is unrelated but lives in the   *)
(* same file as d2. Three obligations: "check" and "build" target d1, and  *)
(* so depend on d1 and d2. "test" targets the artifact that "build"        *)
(* produces, so it also depends on the compiler. An obligation is planned  *)
(* when no record matches its current key.                                 *)
(*                                                                         *)
(* Each record also carries what the result really depended on. That is    *)
(* the ground truth the kernel's keys are judged against.                  *)
(*                                                                         *)
(* Granularity "definition" hashes each definition; "file" hashes the      *)
(* whole file a definition is in, which is the fallback when a language    *)
(* cannot name definitions.                                                *)
(*                                                                         *)
(* Not covered: dependency sets that change, more than one build target,   *)
(* and runs that take time.                                                *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS Granularity, Mutant

VARIABLES defHash, compiler, runner, records

vars == <<defHash, compiler, runner, records>>

Defs        == {"d1", "d2", "d3"}
Hashes      == {0, 1}
Obligations == {"check", "build", "test"}
Target      == {"d1", "d2"}            \* the closure of d1 over depends-on
SameFile(d) == IF d = "d1" THEN {"d1"} ELSE {"d2", "d3"}

Mutants == {"none", "direct_deps_only", "key_omits_producer", "plan_everything"}
ASSUME Mutant \in Mutants /\ Granularity \in {"definition", "file"}

\* How the kernel identifies one definition.
Ident(d) == IF Granularity = "file" THEN [x \in SameFile(d) |-> defHash[x]] ELSE defHash[d]

\* The definitions the kernel's key covers. The planted defect follows only
\* the direct target and misses what it depends on.
KeyDefs == IF Mutant = "direct_deps_only" THEN {"d1"} ELSE Target

BuildKey == [defs |-> [d \in KeyDefs |-> Ident(d)], tool |-> compiler]

Key(o) ==
    CASE o = "check" -> [defs |-> [d \in KeyDefs |-> Ident(d)]]
      [] o = "build" -> BuildKey
      [] o = "test"  -> [producer |-> IF Mutant = "key_omits_producer" THEN 0 ELSE BuildKey,
                         tool |-> runner]

\* What a result really depends on.
Truth(o) ==
    CASE o = "check" -> <<defHash["d1"], defHash["d2"]>>
      [] o = "build" -> <<defHash["d1"], defHash["d2"], compiler>>
      [] o = "test"  -> <<defHash["d1"], defHash["d2"], compiler, runner>>

Reusable(o) == {r \in records : r.ob = o /\ r.key = Key(o)}

Plan == IF Mutant = "plan_everything" THEN Obligations
        ELSE {o \in Obligations : Reusable(o) = {}}

Init ==
    /\ defHash \in [Defs -> Hashes]
    /\ compiler \in Hashes
    /\ runner \in Hashes
    /\ records = {}

Edit(d, h) ==
    /\ h # defHash[d]
    /\ defHash' = [defHash EXCEPT ![d] = h]
    /\ UNCHANGED <<compiler, runner, records>>

RepinCompiler(h) == h # compiler /\ compiler' = h /\ UNCHANGED <<defHash, runner, records>>
RepinRunner(h)   == h # runner /\ runner' = h /\ UNCHANGED <<defHash, compiler, records>>

\* A planned obligation runs. The test runs only on an artifact from a build
\* that is itself current.
Run(o) ==
    /\ o \in Plan
    /\ o = "test" => Reusable("build") # {}
    /\ records' = records \cup {[ob |-> o, key |-> Key(o), truth |-> Truth(o)]}
    /\ UNCHANGED <<defHash, compiler, runner>>

Next ==
    \/ \E d \in Defs, h \in Hashes : Edit(d, h)
    \/ \E h \in Hashes : RepinCompiler(h) \/ RepinRunner(h)
    \/ \E o \in Obligations : Run(o)

Spec == Init /\ [][Next]_vars

RecordBound == Cardinality(records) <= 3
----------------------------------------------------------------------------
\* Every record the kernel would reuse really was produced from the current
\* inputs. This is "no wrong reuse", and so "everything stale is planned".
NoWrongReuse ==
    \A o \in Obligations : \A r \in Reusable(o) : r.truth = Truth(o)

\* Nothing is planned that already has a result for the current inputs.
\* Holds with definition granularity. With file granularity it is expected
\* to be VIOLATED: coarse identity costs extra reruns, and only that.
NoNeedlessRerun ==
    \A o \in Plan : ~\E r \in records : r.ob = o /\ r.truth = Truth(o)

\* Reachability: expected to be VIOLATED.
NeverReused == \A o \in Obligations : Reusable(o) = {} \/ records = {}
NeverAllCurrent == Plan # {}
=============================================================================
