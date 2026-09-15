from __future__ import annotations

import os
import sys
from pathlib import Path


def get_sumo_home() -> Path:
    value = os.environ.get("SUMO_HOME")
    if not value:
        raise EnvironmentError("SUMO_HOME is not set")
    return Path(value).expanduser().resolve()


def sumo_tools_path() -> Path:
    base = get_sumo_home()
    candidates = [
        base / "tools",
        base / "share" / "sumo" / "tools",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not find SUMO tools under {base}")


def ensure_sumo_tools_on_path() -> Path:
    tools = sumo_tools_path()
    tools_str = str(tools)
    if tools_str not in sys.path:
        sys.path.insert(0, tools_str)
    return tools

