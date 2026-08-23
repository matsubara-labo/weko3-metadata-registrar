# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "selenium>=4.33.0",
#   "python-dotenv>=1.1.0",
# ]
# ///
#
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from importers.selenium_auto_register import main

if __name__ == "__main__":
    raise SystemExit(main())
