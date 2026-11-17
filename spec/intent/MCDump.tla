------------------------------ MODULE MCDump ------------------------------
(* The intent model with the kernel's answer written into every state:     *)
(* `report` is what the model says is delivered and fulfilled.             *)
EXTENDS MC

VARIABLE report

Answer == [delivered |-> ReportDelivered, fulfilled |-> ReportFulfilled]

DumpInit == Init /\ report = Answer
DumpNext == Next /\ report' = Answer'
DumpSpec == DumpInit /\ [][DumpNext]_<<vars, report>>
=============================================================================
