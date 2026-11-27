"""The "now showing" pointer shared by the MCP server and the web viewer.

The MCP server (run by Claude) and the viewer server are separate processes,
so they meet through a small JSON file. The viewer polls it and reloads when
`version` changes.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from aicad.registry import project_root


def state_file() -> Path:
    d = Path(os.environ.get("AICAD_STATE_DIR", project_root() / ".aicad"))
    d.mkdir(parents=True, exist_ok=True)
    return d / "current.json"


def set_current(name: str, params: dict[str, Any]) -> dict[str, Any]:
    state = {"name": name, "params": params, "version": time.time_ns()}
    tmp = state_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(state_file())
    return state


def get_current() -> dict[str, Any] | None:
    try:
        return json.loads(state_file().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
