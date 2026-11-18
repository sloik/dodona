------------------------------ MODULE Planner ------------------------------
(***************************************************************************)
(* What the planner reruns (claims C8, C9 and C10).                        *)
(*                                                                         *)
(* Five definitions; d2 and d3 share a file. The depends-on relation is   *)
(* one of two shapes, a chain three steps deep or a diamond, chosen at the *)
(* start of each behaviour. "check" and "build" target d1; "test" works   *)
(* on the artifact a build produced. A compiler and a test runner can be   *)
(* repinned.                                                               *)
(*                                                                         *)
(* Two descriptions are kept apart on purpose. The SPECIFICATION finds     *)
(* what d1 depends on by following the relation until nothing new turns   *)
(* up, and the truth of a test is the artifact it actually ran on. The     *)
(* KERNEL builds its key from an index that follows the relation in a      *)
(* fixed number of passes, and looks the artifact up by key. The           *)
(* properties compare what the kernel would reuse and plan with what the   *)
(* specification calls for, in both directions.                            *)
(*                                                                         *)
(* Not covered: builds that fail, more than one build target, runs that    *)
(* take time, and any behaviour longer than MaxSteps steps.                *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS Granularity, Mutant

VARIABLES deps, defHash, compiler, runner, records, store, latest, steps

vars == <<deps, defHash, compiler, runner, records, store, latest, steps>>

\* The search is bounded by depth: every behaviour of at most this many steps
\* from one starting state. Bounding the number of records instead left a
\* state space too large to finish.
MaxSteps == 6

Defs        == {"d1", "d2", "d3", "d4", "d5"}
Hashes      == {0, 1}
Obligations == {"check", "build", "test"}
SameFile(d)  == IF d \in {"d2", "d3"} THEN {"d2", "d3"} ELSE {d}

\* The depends-on relation is not fixed: each behaviour starts from one of two shapes, a chain
\* three steps deep and a diamond, so a key that follows the relation wrongly shows.
Chain   == [d \in Defs |-> CASE d = "d1" -> {"d2"} [] d = "d2" -> {"d4"} [] d = "d4" -> {"d5"} [] OTHER -> {}]
Diamond == [d \in Defs |-> CASE d = "d1" -> {"d2", "d4"} [] d = "d4" -> {"d5"} [] OTHER -> {}]

(* The specification: everything d depends on, found by following the relation until nothing new
   turns up. *)
RECURSIVE Reach(_)
Reach(S) == LET more == S \cup UNION {deps[x] : x \in S} IN IF more = S THEN S ELSE Reach(more)
TrueClosure(d) == Reach({d})

(* The kernel: it follows the relation a fixed number of times, as an index built in passes does.
   That is right while the passes are at least as many as the deepest chain. *)
Step(S)    == S \cup UNION {deps[x] : x \in S}
Passes     == IF Mutant = "closure_two_passes" THEN 2 ELSE Cardinality(Defs)
RECURSIVE StepN(_, _)
StepN(S, n) == IF n = 0 THEN S ELSE StepN(Step(S), n - 1)
Closure(d) == StepN({d}, Passes)

Mutants == {"none", "direct_deps_only", "no_deps", "closure_two_passes", "key_omits_producer",
            "build_key_omits_compiler", "plan_everything", "plan_nothing", "test_without_build"}
ASSUME Mutant \in Mutants /\ Granularity \in {"definition", "file"}

\* How the kernel identifies one definition.
Ident(d) == IF Granularity = "file" THEN [x \in SameFile(d) |-> defHash[x]] ELSE defHash[d]

\* The definitions the kernel's key covers.
KeyDefs == CASE Mutant = "no_deps"          -> {"d1"}
             [] Mutant = "direct_deps_only" -> Step({"d1"})
             [] OTHER                       -> Closure("d1")

BuildKey == IF Mutant = "build_key_omits_compiler" THEN [defs |-> [d \in KeyDefs |-> Ident(d)], tool |-> 0]
            ELSE [defs |-> [d \in KeyDefs |-> Ident(d)], tool |-> compiler]

Key(o) ==
    CASE o = "check" -> [defs |-> [d \in KeyDefs |-> Ident(d)]]
      [] o = "build" -> BuildKey
      [] o = "test"  -> [producer |-> IF Mutant = "key_omits_producer" THEN 0 ELSE BuildKey,
                         tool |-> runner]

\* What a source-level result really depends on: the true closure, now, found by the specification.
Sources == [d \in TrueClosure("d1") |-> defHash[d]]

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

Plan == CASE Mutant = "plan_everything" -> Obligations
          [] Mutant = "plan_nothing" -> {}
          [] OTHER -> {o \in Obligations : Reusable(o) = {}}

Init ==
    /\ deps \in {Chain, Diamond}
    /\ defHash = [d \in Defs |-> 0]
    /\ compiler = 0
    /\ runner = 0
    /\ steps = 0
    /\ records = {}
    /\ store = {}
    /\ latest = [sources |-> [d \in TrueClosure("d1") |-> 0], compiler |-> 0]  \* a placeholder; read only once something is built

Edit(d, h) ==
    /\ h # defHash[d]
    /\ defHash' = [defHash EXCEPT ![d] = h]
    /\ UNCHANGED <<deps, compiler, runner, records, store, latest>>

RepinCompiler(h) == h # compiler /\ compiler' = h /\ UNCHANGED <<deps, defHash, runner, records, store, latest>>
RepinRunner(h)   == h # runner /\ runner' = h /\ UNCHANGED <<deps, defHash, compiler, records, store, latest>>

\* A planned obligation runs. A build stores its artifact under its key. A
\* test may run only when the build for the current inputs has been done, and
\* takes that build's artifact. The planted defect runs the test on whatever
\* was built last, current or not.
Run(o) ==
    /\ o \in Plan
    /\ o = "test" => IF Mutant = "test_without_build" THEN store # {} ELSE Stored # {}
    /\ records' = records \cup {[ob |-> o, key |-> Key(o), truth |-> TruthNow(o)]}
    /\ LET made == [sources |-> Sources, compiler |-> compiler]
       IN  /\ store' = IF o = "build" THEN store \cup {[key |-> BuildKey, content |-> made]} ELSE store
           /\ latest' = IF o = "build" THEN made ELSE latest
    /\ UNCHANGED <<deps, defHash, compiler, runner>>

Next ==
    /\ steps < MaxSteps
    /\ steps' = steps + 1
    /\ \/ \E d \in Defs, h \in Hashes : Edit(d, h)
       \/ \E h \in Hashes : RepinCompiler(h) \/ RepinRunner(h)
       \/ \E o \in Obligations : Run(o)

Spec == Init /\ [][Next]_vars

----------------------------------------------------------------------------
TypeOK ==
    /\ deps \in {Chain, Diamond}
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

\* And the other way round: whatever has no result resting on the right things is planned. A
\* planner that plans nothing reuses nothing wrongly, and is useless.
PlanComplete ==
    \A o \in Obligations : (~\E r \in records : r.ob = o /\ r.truth = TruthWanted(o)) => o \in Plan

\* Reachability: expected to be VIOLATED.
NeverAllCurrent == Plan # {}
=============================================================================
