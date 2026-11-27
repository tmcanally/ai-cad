"""File exports for machines. STL for 3D printing today; DXF/SVG for laser and CNC next."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from build123d import export_stl

from aicad.design import Design

STL_TOLERANCE = 0.01  # mm of chordal deviation; fine enough for FDM and resin
STL_ANGULAR = 0.1


def part_stl_bytes(design: Design, part: str) -> bytes:
    shape = design.part(part).shape
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{part}.stl"
        if not export_stl(shape, path, tolerance=STL_TOLERANCE, angular_tolerance=STL_ANGULAR):
            raise RuntimeError(f"STL export failed for part {part!r}")
        return path.read_bytes()


def write_stls(design: Design, out_dir: Path) -> list[Path]:
    """Write one binary STL per part, named <design>-<part>.stl."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for p in design.parts:
        path = out_dir / f"{design.name}-{p.name}.stl"
        path.write_bytes(part_stl_bytes(design, p.name))
        paths.append(path)
    return paths


def stl_zip_bytes(design: Design) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in design.parts:
            zf.writestr(f"{design.name}-{p.name}.stl", part_stl_bytes(design, p.name))
    return buf.getvalue()
