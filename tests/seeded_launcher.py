"""Launch the real game with a fixed shuffle (CSBJ_SEED, else 20260929 -- the game shuffles with the global
RNG), so the hands a screen check looks at are dealt the same every run. Used by check_ui.py; runs as its own
process."""
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
random.seed(int(os.environ.get("CSBJ_SEED", "20260929")))
from blackjack import ui  # noqa: E402

ui.run()
