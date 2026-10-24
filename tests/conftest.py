import sys
from pathlib import Path

# `pytest` (the console script) does not put the repository root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
