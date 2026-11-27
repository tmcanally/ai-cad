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

from aicad import checks, export, history, printing, registry, state

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
- For sliding parts, a LinearJoint and Motion.from_linear_joint(...) work the same way.
- When a motion changes shape rather than just position (fabric folding, several
  parts moving by different rules), make the position a Param and add
  Motion.from_param("name", "param_name", (lo, hi)); the viewer animates it by
  rebuilding the design across that range. See the built-in `roman_shade`.
- See the built-in `hinged_box` (read_design_source) for a full example.

Keep it fully parametric:
- Every size, gap, thickness, hole, count or angle a person might want to change
  is a Param with a plain-words description, a sensible min/max and a unit, and
  build() derives everything else from those. Name params after what the person
  would call them ("inner_height", "screw_diameter"), not after code.
- write_design returns `warnings` from a parameter check (PARAMS vs build()
  arguments, bare numbers in build()). Fix them unless they are ratios or tolerances.

The design loop with a person:
1. They describe an object. Ask at most one question if something essential is
   missing (e.g. the size of the thing it must fit); otherwise pick sensible values,
   write the design, and tell them which parameters it has.
2. "Make it taller", "5 mm wider", "M3 screws": a value change. Use set_params,
   which saves the values so they survive reloads and later rewrites. Use
   build_design only to preview values without keeping them.
3. "Add mounting tabs", "round the corners": a shape change. read_design_source,
   edit it, and write_design with a short `note` saying what changed. New
   dimensions become new Params. Saved values carry over.
4. "Go back", "undo that": undo_design, or list_versions and restore_version.
'''

mcp = MCPServer(
    name="aicad",
    instructions=(
        "AI CAD: parametric CAD on build123d with a live 3D viewer at "
        f"{VIEWER_URL}. Use list_designs, read_design_source, write_design, "
        "set_params, build_design, undo_design, list_versions, restore_version "
        "export_stl and prepare_print.\n" + DESIGN_CONTRACT
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
def write_design(name: str, source: str, note: str = "") -> dict[str, Any]:
    """Save a design file to designs/<name>.py, build it to check it, and show it in the viewer.

    `name` is lower_snake_case. `source` is the full Python file; see the server
    instructions for the required shape. `note` says in a few words what changed
    ("added wall-mount tabs"); it labels this version in the history.

    Saved parameter values (from set_params or the viewer) still apply after a
    rewrite, for every parameter the new source still has.

    Returns a summary with `version` and parameter-check `warnings`, or the error
    and traceback if the build failed (the file is kept so you can fix it, and no
    version is recorded until it builds).
    """
    history.ensure_baseline(name)
    path = registry.save_design(name, source)
    try:
        result = _summary(name, None)
    except Exception as exc:
        return {"saved_to": str(path), "error": str(exc), "traceback": traceback.format_exc(limit=8)}
    result["saved_to"] = str(path)
    result["warnings"] = checks.check_module(registry._load_module(name, path), source)
    result["version"] = history.snapshot(name, note or "Wrote design")["version"]
    return result


@mcp.tool()
def set_params(name: str, params: dict[str, float], note: str = "") -> dict[str, Any]:
    """Change parameter values and keep them: rebuilds, shows the result, and records a version.

    Use this when the person asks for a different size or count ("make it 10 mm
    taller"). Only the parameters you pass change; others keep their saved values.
    """
    try:
        version = history.save_params(name, params, note)
        result = _summary(name, None)
    except Exception as exc:
        return {"error": str(exc), "traceback": traceback.format_exc(limit=8)}
    result["version"] = version["version"]
    return result


@mcp.tool()
def list_versions(name: str) -> list[dict[str, Any]]:
    """The design's history, oldest first: version number, time, what changed, and the saved values."""
    return history.list_versions(name)


@mcp.tool()
def restore_version(name: str, version: int) -> dict[str, Any]:
    """Bring back an earlier version (its source and its saved values). Recorded as a new version."""
    try:
        meta = history.restore(name, version)
        result = _summary(name, None)
    except Exception as exc:
        return {"error": str(exc)}
    result["version"] = meta["version"]
    result["restored"] = meta["note"]
    return result


@mcp.tool()
def undo_design(name: str) -> dict[str, Any]:
    """Step back to the version before the current one. Calling it again keeps stepping back."""
    try:
        meta = history.undo(name)
        result = _summary(name, None)
    except Exception as exc:
        return {"error": str(exc)}
    result["version"] = meta["version"]
    result["restored"] = meta["note"]
    return result


@mcp.tool()
def build_design(name: str, params: dict[str, float] | None = None) -> dict[str, Any]:
    """Preview a design with optional parameter overrides and show it in the viewer, without saving them.

    To keep new values, use set_params instead.

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


@mcp.tool()
def prepare_print(
    name: str,
    params: dict[str, float] | None = None,
    settings: dict[str, Any] | None = None,
    part_settings: dict[str, dict[str, Any]] | None = None,
    slice: bool = True,
    out_dir: str | None = None,
) -> dict[str, Any]:
    """Make print-ready files for a 3D printer (default: AnkerMake M5, 235 x 235 x 250 mm).

    Picks every printed part (parts whose material starts with "Buy", or names
    metal, wood, fabric or filament pins, are left out), chooses the side each
    one sits on (fewest overhangs, steady footprint; parts too long to lie
    straight go across the diagonal), turns supports on only where overhangs
    remain, adds a brim to tall or small-footprint parts, and packs everything
    onto as few plates as it can (one filament per plate). Each plate becomes a
    .3mf project (opens in AnkerMake Studio, PrusaSlicer or OrcaSlicer with parts
    in place) and, when PrusaSlicer is installed, a sliced .gcode. Plates over
    `max_plate_hours` are split. Also writes PRINT-LIST.md and plan.json.

    `settings` (whole job, all optional): printer ("ankermake_m5"), filament
    ("auto" from each part's material, or PLA, PLA+, PETG, ABS), layer_height
    (0.2), spacing (6 mm), max_plate_hours (24), plus any per-part setting to
    apply to every part.
    `part_settings`: {part name: {...}} with orientation ("auto" or the side on
    the bed: bottom, top, front, back, left, right), supports (auto/on/off),
    infill (percent, 20), walls (3), brim (mm or "auto"), copies (1).
    A design can set per-part defaults with Part(print_settings={...}).

    Returns plates (parts, files, print time, grams), each piece's chosen
    orientation and settings with the reason, parts not printed, and parts too
    big for the bed. Tell the person the plates, time and filament, and any
    choices worth a second look.
    """
    try:
        design, resolved = registry.build(name, params)
        plan = printing.plan_print(design, settings, part_settings)
        printer = plan.job.printer
        target = Path(out_dir) if out_dir else registry.project_root() / "exports" / name / printer
        summary = printing.write_print_job(plan, design, target, slice=slice)
    except Exception as exc:
        return {"error": str(exc), "traceback": traceback.format_exc(limit=8)}
    summary["params"] = resolved
    summary["viewer"] = f"{VIEWER_URL}/?design={name}"
    return summary
