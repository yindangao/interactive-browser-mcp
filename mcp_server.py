"""Backward-compatible entry point for interactive-browser-mcp."""

import asyncio
import sys
from pathlib import Path

# Ensure package root is on sys.path
package_root = Path(__file__).resolve().parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

# Ensure dedicated venv site-packages are accessible if not in current environment
try:
    import playwright
except ImportError:
    local_venv = package_root / ".venv/lib/python3.12/site-packages"
    if local_venv.exists() and str(local_venv) not in sys.path:
        sys.path.insert(0, str(local_venv))

from browser_mcp.server import (
    server,
    session_instance as session_manager,
    handle_list_tools as list_tools,
    handle_call_tool as call_tool,
    main,
)

__all__ = ["server", "session_manager", "list_tools", "call_tool", "main"]

if __name__ == "__main__":
    asyncio.run(main())
