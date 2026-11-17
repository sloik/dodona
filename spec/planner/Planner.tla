------------------------------ MODULE Planner ------------------------------
(***************************************************************************)
(* What the planner reruns, and in what order (claims C8, C9 and C10).     *)
(*                                                                         *)
(* Four definitions in a chain: d1 depends on d2, which depends on d4. d3  *)
(* is unrelated but lives in the same file as d2. "check" and "build"      *)
(* target d1. "test" works on the artifact that "build" produced.          *)
(*                                                                         *)
(* The model keeps two things apart on purpose. The kernel's KEY for an    *)
(* obligation is what the kernel hashes. The TRUTH of a result is what it  *)
(* really came from: for a check or a build, the content of everything d1  *)
(* depends on, found by following the depends-on relation; for a test, the *)
(* artifact it actually ran on. Builds put their artifacts in a store,     *)
(* each under the key of the build that made it. A test must take the      *)
(* artifact stored under the current build key, not whichever artifact was *)
(* built last. The properties compare key and truth.                       *)
(*                                                                         *)
(* Not covered: dependency relations that change, builds that fail, more   *)
(* than one build target, runs that take time, and any behaviour longer    *)
(* than MaxSteps steps.                                                    *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS Granularity, Mutant

VARIABLES defHash, compiler, runner, records, store, latest, steps

vars == <<defHash, compiler, runner, records, store, latest, steps>>

\* The search is bounded by depth: every behaviour of at most this many steps
\* from one starting state. Bounding the number of records instead left a
\* state space too large to finish.
MaxSteps == 6

Defs        == {"d1", "d2", "d3", "d4"}
Hashes      == {0, 1}
Obligations == {"check", "build", "test"}
DependsOn(d) == CASE d = "d1" -> {"d2"} [] d = "d2" -> {"d4"} [] OTHER -> {}
SameFile(d)  == IF d \in {"d2", "d3"} THEN {"d2", "d3"} ELSE {d}

\* Everything reachable from d over depends-on, in at most three steps.
Step(S)    == S \cup UNION {DependsOn(d) : d \in S}
Closure(d) == Step(Step(Step({d})))

Mutants == {"none", "direct_deps_only", "no_deps", "key_omits_producer", "plan_everything",
            "test_without_build"}
ASSUME Mutant \in Mutants /\ Granularity \in {"definition", "file"}

\* How the kernel identifies one definition.
Ident(d) == IF Granularity = "file" THEN [x \in SameFile(d) |-> defHash[x]] ELSE defHash[d]

\* The definitions the kernel's key covers.
KeyDefs == CASE Mutant = "no_deps"          -> {"d1"}
             [] Mutant = "direct_deps_only" -> Step({"d1"})
             [] OTHER                       -> Closure("d1")

BuildKey == [defs |-> [d \in KeyDefs |-> Ident(d)], tool |-> compiler]

Key(o) ==
    CASE o = "check" -> [defs |-> [d \in KeyDefs |-> Ident(d)]]
      [] o = "build" -> BuildKey
      [] o = "test"  -> [producer |-> IF Mutant = "key_omits_producer" THEN 0 ELSE BuildKey,
                         tool |-> runner]

\* What a source-level result really depends on: the true closure, now.
Sources == [d \in Closure("d1") |-> defHash[d]]

\* The artifact a test run now would use: the one stored under the current
\* build key. The planted defect takes whichever was built last.
Stored == {s \in store : s.key = BuildKey}
Tested == IF Mutant = "test_without_build" THEN latest
          ELSE (CHOOSE s \in Stored : TRUE).content

\* What a result produced now would really rest on.
TruthNow(o) ==
    CASE o = "check" -> [sources |-> Sources]
      [] o = "build" -> [sources |-> Sources, compiler |-> compiler]
      [] o = "test"  -> [artifact |-> Tested, runner |-> runner]

\* What a result for the current inputs ought to rest on. For the test that is
\* an artifact built from the current sources by the current compiler.
TruthWanted(o) ==
    IF o = "test" THEN [artifact |-> [sources |-> Sources, compiler |-> compiler], runner |-> runner]
    ELSE TruthNow(o)

Reusable(o) == {r \in records : r.ob = o /\ r.key = Key(o)}

Plan == IF Mutant = "plan_everything" THEN Obligations
        ELSE {o \in Obligations : Reusable(o) = {}}

Init ==
    /\ defHash = [d \in Defs |-> 0]
    /\ compiler = 0
    /\ runner = 0
    /\ steps = 0
    /\ records = {}
    /\ store = {}
    /\ latest = "none"

Edit(d, h) ==
    /\ h # defHash[d]
    /\ defHash' = [defHash EXCEPT ![d] = h]
    /\ UNCHANGED <<compiler, runner, records, store, latest>>

RepinCompiler(h) == h # compiler /\ compiler' = h /\ UNCHANGED <<defHash, runner, records, store, latest>>
RepinRunner(h)   == h # runner /\ runner' = h /\ UNCHANGED <<defHash, compiler, records, store, latest>>

\* A planned obligation runs. A build stores its artifact under its key. A
\* test may run only when the build for the current inputs has been done, and
\* takes that build's artifact. The planted defect runs the test on whatever
\* was built last, current or not.
Run(o) ==
    /\ o \in Plan
    /\ o = "test" => IF Mutant = "test_without_build" THEN latest # "none" ELSE Stored # {}
    /\ records' = records \cup {[ob |-> o, key |-> Key(o), truth |-> TruthNow(o)]}
    /\ LET made == [sources |-> Sources, compiler |-> compiler]
       IN  /\ store' = IF o = "build" THEN store \cup {[key |-> BuildKey, content |-> made]} ELSE store
           /\ latest' = IF o = "build" THEN made ELSE latest
    /\ UNCHANGED <<defHash, compiler, runner>>

Next ==
    /\ steps < MaxSteps
    /\ steps' = steps + 1
    /\ \/ \E d \in Defs, h \in Hashes : Edit(d, h)
       \/ \E h \in Hashes : RepinCompiler(h) \/ RepinRunner(h)
       \/ \E o \in Obligations : Run(o)

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
TypeOK ==
    /\ defHash \in [Defs -> Hashes]
    /\ compiler \in Hashes /\ runner \in Hashes
    /\ steps \in 0..MaxSteps
    /\ \A r \in records : r.ob \in Obligations
    /\ Granularity \in {"definition", "file"}

\* Every record the kernel would reuse rests on what a result for the current
\* inputs ought to rest on. For a test that includes having been run on an
\* artifact built from the current sources.
NoWrongReuse ==
    \A o \in Obligations : \A r \in Reusable(o) : r.truth = TruthWanted(o)

\* Nothing is planned that already has a result resting on the right things.
\* Holds with definition granularity. With file granularity it is expected
\* to be VIOLATED: coarse identity costs extra reruns, and only that.
NoNeedlessRerun ==
    \A o \in Plan : ~\E r \in records : r.ob = o /\ r.truth = TruthWanted(o)

\* Reachability: expected to be VIOLATED.
NeverAllCurrent == Plan # {}
=============================================================================
