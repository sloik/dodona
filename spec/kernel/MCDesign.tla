----------------------------- MODULE MCDesign -----------------------------
(* The main design check, with a state view that leaves out `changed`.     *)
(*                                                                         *)
(* `changed` is a history variable used only by the reachability property  *)
(* NeverReusedAfterChange. No action reads it to decide what the other     *)
(* variables do, and none of the properties checked in design.cfg mention  *)
(* it. Two states that differ only in `changed` therefore have the same    *)
(* future as far as those properties can tell, and treating them as one    *)
(* state loses nothing. It keeps the search within the checker's disk      *)
(* limits at the full bounds.                                              *)
EXTENDS MC

DesignView == <<defHash, toolHash, backend, running, ledger, completed>>
=============================================================================
