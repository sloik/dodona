---
id: "0006"
title: The path from an intent to what was delivered can be traced and scored
owner: project owner
worker: the agents building dodona
parent: "0001"
touches:
  - MODEL.md
  - spec/
criteria: [{"id": "1", "words": "Intent status, gates, assurance and amendments are modelled, with a planted defect for each rule", "gate": "hard", "checked_by": "Run 9 in spec/CLAIMS.md checked C23, C24 and C25 in bounded models with planted defects. C26 and C27 remain unmodelled."}, {"id": "2", "words": "A self-granted exception is always shown first and never counts where an independent approver is required", "gate": "hard", "checked_by": "Run 9 in spec/CLAIMS.md checked self-grant grading and the separation floor in C33. Showing a self-grant first in the status report remains open. C32 tracks the headline."}, {"id": "3", "words": "The intent and amendment formats have schemas", "gate": "hard", "checked_by": "The draft provider protocol defines JSON message shapes for intents and amendments. Validation of handwritten project files against those shapes remains unshown."}]
---

# 0006. The path from an intent to what was delivered can be traced and scored

For any intent, dodona can show each link from the plain words to the running system, how strong each link is, and every exception that was granted on the way.

## Criteria

<!-- criteria: written by tools/intents.py from the front matter; do not edit -->
| # | Criterion | Gate | Checked by | Observed after delivery |
|---|---|---|---|---|
| 1 | Intent status, gates, assurance and amendments are modelled, with a planted defect for each rule | hard | nothing a kernel reads yet. Run 9 in spec/CLAIMS.md checked C23, C24 and C25 in bounded models with planted defects. C26 and C27 remain unmodelled. |  |
| 2 | A self-granted exception is always shown first and never counts where an independent approver is required | hard | nothing a kernel reads yet. Run 9 in spec/CLAIMS.md checked self-grant grading and the separation floor in C33. Showing a self-grant first in the status report remains open. C32 tracks the headline. |  |
| 3 | The intent and amendment formats have schemas | hard | nothing a kernel reads yet. The draft provider protocol defines JSON message shapes for intents and amendments. Validation of handwritten project files against those shapes remains unshown. |  |
<!-- end of criteria -->
