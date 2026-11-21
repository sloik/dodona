"""Read dodona's intent files, and write the criteria table each one shows. Stage-0 helper (decision 0028).

    python tools/intents.py --write   # rewrite each intent's table from its front matter
    python tools/intents.py           # fail unless every intent file can be read one way only

The reading is the intents provider's (providers/intents/intents_md.py), so what this checks is what
the provider answers.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "providers" / "intents"))
from intents_md import *  # noqa: E402,F401,F403 - every name of the reader, for the tools that import this one
from intents_md import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
