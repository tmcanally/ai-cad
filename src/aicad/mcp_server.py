"""MCP server so Claude (Desktop or Code) can create, build, show and export designs.

Run with `aicad mcp` (stdio). Every build also updates the "now showing"
pointer, so an open viewer tab switches to whatever Claude just built.
"""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

from aicad import export, registry, state

VIEWER_URL = os.environ.get("AICAD_VIEWER_URL", "http://127.0.0.1:8765")

DESIGN_CONTRACT = '''
A design is one Python file using build123d (algebra mode recommended):

    from build123d import *
    from aicad.design import Design, Motion, Param, Part

    TITLE = "Phone stand"
    DESCRIPTION = "One-line summary"
    PARAMS = {"width": Param(70, 40, 120, description="Overall width")}   # numbers only

    def build(width=70) -> Design:
        body = Box(width, 50, 5)
        return Design(name="phone_stand", parts=[
            Part("body", body, color="#4f7cac", explode=(0, 0, 0), material="PLA"),
        ])

Rules:
- Units are millimetres, Z is up. Place each Part where it sits when assembled.
- `explode` is the part's offset in mm at 100% explode in the viewer.
- For moving parts, use build123d joints: a RevoluteJoint on the parent, a
  RigidJoint on the child, then joint.connect_to(child_joint, angle=0) to place it,
  and add Motion.from_revolute_joint("name", joint, parts=["child"]).
- See the built-in `hinged_box` (read_design_source) for a full example.
'''

mcp = MCPServer(
    name="aicad",
    instructions=(
        "AI CAD: parametric CAD on build123d with a live 3D viewer at "
        f"{VIEWER_URL}. Use list_designs, read_design_source, write_design, "
        "build_design and export_stl.\n" + DESIGN_CONTRACT
    ),
)


def _summary(name: str, params: dict[str, Any] | None) -> dict[str, Any]:
    design, resolved = registry.build(name, params)
    state.set_current(name, resolved)
    out = design.summary()
    out["params"] = resolved
    out["viewer"] = f"{VIEWER_URL}/?design={name}"
    return out


@mcp.tool()
def list_designs() -> list[dict[str, Any]]:
    """List available designs with their title, description and parameters."""
    return [d.to_dict() for d in registry.list_designs()]


@mcp.tool()
def read_design_source(name: str) -> str:
    """Return the Python source of a design, to study it or base a new one on it."""
    path, _ = registry.get_path(name)
    return path.read_text()


@mcp.tool()
def write_design(name: str, source: str) -> dict[str, Any]:
    """Save a design file to designs/<name>.py, build it to check it, and show it in the viewer.

    `name` is lower_snake_case. `source` is the full Python file; see the server
    instructions for the required shape. Returns a summary, or the error and
    traceback if the build failed (the file is kept so you can fix it).
    """
    path = registry.save_design(name, source)
    try:
        result = _summary(name, None)
        result["saved_to"] = str(path)
        return result
    except Exception as exc:
        return {"saved_to": str(path), "error": str(exc), "traceback": traceback.format_exc(limit=8)}


@mcp.tool()
def build_design(name: str, params: dict[str, float] | None = None) -> dict[str, Any]:
    """Build a design with optional parameter overrides and show it in the viewer.

    Returns each part's size, volume and validity, the joint motions, and the viewer URL.
    """
    try:
        return _summary(name, params)
    except Exception as exc:
        return {"error": str(exc), "traceback": traceback.format_exc(limit=8)}


@mcp.tool()
def export_stl(name: str, params: dict[str, float] | None = None, out_dir: str | None = None) -> dict[str, Any]:
    """Export one binary STL per part for 3D printing. Defaults to exports/<name>/ in the project."""
    design, resolved = registry.build(name, params)
    target = Path(out_dir) if out_dir else registry.project_root() / "exports" / name
    paths = export.write_stls(design, target)
    return {"params": resolved, "files": [str(p) for p in paths]}


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
