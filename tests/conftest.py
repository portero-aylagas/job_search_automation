from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
