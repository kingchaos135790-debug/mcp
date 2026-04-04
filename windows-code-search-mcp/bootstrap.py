from __future__ import annotations

import os
import sys
from pathlib import Path


WINDOWS_MCP_DIR = Path(os.getenv("WINDOWS_MCP_DIR", r"E:\Program Files\mcp\Windows-MCP"))
WINDOWS_MCP_SRC = WINDOWS_MCP_DIR / "src"

if str(WINDOWS_MCP_SRC) not in sys.path:
    sys.path.insert(0, str(WINDOWS_MCP_SRC))
