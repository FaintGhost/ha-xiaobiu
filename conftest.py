from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable so `custom_components.xiaobiu` resolves.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
  sys.path.insert(0, str(PROJECT_ROOT))
