"""Print-ready output for FDM printers: orient, arrange, slice.

`plan_print(design)` picks every printable part, chooses how each one should
sit on the bed (fewest overhangs, steady footprint), decides supports, brim,
walls and infill, and packs the pieces onto as few build plates as it can.
`write_print_job(plan, out_dir)` writes one PrusaSlicer project (.3mf) per
plate, with every part's own settings inside it, and slices each one to
G-code with PrusaSlicer's command line when a slicer is installed.

The .3mf files open in AnkerMake Studio, PrusaSlicer and OrcaSlicer with the
parts already in place, so they can be checked or tweaked before printing.

Every choice is a default a person can override, globally or per part:

    plan_print(design, settings={"filament": "PETG", "infill": 30},
               part_settings={"headrail_1": {"orientation": "back", "supports": "on"}})

A design can also set its own defaults on a Part with `print_settings={...}`.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import numpy as np

from aicad.design import Design, Part

PRINTERS_DIR = Path(__file__).resolve().parent / "printers"

# --------------------------------------------------------------------------------------
# Printers and filaments
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Printer:
    id: str
    name: str
    bed: tuple[float, float]
    height: float
    profile: str
    """PrusaSlicer .ini in aicad/printers/ with the machine and base print settings."""
    margin: float = 3.0
    """Kept clear at the bed edges (room for the skirt)."""


PRINTERS: dict[str, Printer] = {
    "ankermake_m5": Printer("ankermake_m5", "AnkerMake M5", (235.0, 235.0), 250.0, "ankermake_m5.ini"),
}

# Temperatures and fans from AnkerMake's own filament presets.
FILAMENTS: dict[str, dict[str, Any]] = {
    "PLA": {"temperature": 200, "first_layer_temperature": 230, "bed_temperature": 60,
            "first_layer_bed_temperature": 60, "min_fan_speed": 100, "max_fan_speed": 100,
            "bridge_fan_speed": 100, "fan_always_on": 1, "disable_fan_first_layers": 1,
            "filament_density": 1.24, "filament_type": "PLA"},
    "PLA+": {"temperature": 200, "first_layer_temperature": 230, "bed_temperature": 65,
             "first_layer_bed_temperature": 65, "min_fan_speed": 100, "max_fan_speed": 100,
             "bridge_fan_speed": 100, "fan_always_on": 1, "disable_fan_first_layers": 1,
             "filament_density": 1.24, "filament_type": "PLA"},
    "PETG": {"temperature": 255, "first_layer_temperature": 255, "bed_temperature": 80,
             "first_layer_bed_temperature": 80, "min_fan_speed": 50, "max_fan_speed": 50,
             "bridge_fan_speed": 100, "fan_always_on": 1, "disable_fan_first_layers": 2,
             "filament_density": 1.27, "filament_type": "PETG"},
    "ABS": {"temperature": 255, "first_layer_temperature": 255, "bed_temperature": 90,
            "first_layer_bed_temperature": 90, "min_fan_speed": 0, "max_fan_speed": 0,
            "bridge_fan_speed": 30, "fan_always_on": 0, "disable_fan_first_layers": 2,
            "filament_density": 1.04, "filament_type": "ABS"},
}

DEFAULT_FILAMENT = "PLA+"

# --------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------

ORIENTATIONS = ("bottom", "top", "front", "back", "left", "right")
"""Which side of the part (as modelled, -Z = bottom, -Y = front, -X = left) goes on the bed."""


def _rx(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


# Rotation that brings each side's outward direction to straight down.
_DOWN = {
    "bottom": np.eye(3),
    "top": _rx(180),
    "front": _rx(90),
    "back": _rx(-90),
    "left": _ry(-90),
    "right": _ry(90),
}


@dataclass
class PartSettings:
    """How one part is printed. Every field accepts "auto" where it says so."""

    orientation: str = "auto"
    """auto, or the side that goes on the bed: bottom, top, front, back, left, right."""
    supports: str = "auto"
    """auto (on when the chosen orientation still has real overhangs), on, or off."""
    infill: float = 20.0
    """Infill density in percent."""
    walls: int = 3
    """Perimeters."""
    brim: Any = "auto"
    """Brim width in mm, or auto (5 mm for tall, narrow or small-footprint parts)."""
    copies: int = 1


@dataclass
class JobSettings:
    """Settings for the whole print job."""

    printer: str = "ankermake_m5"
    filament: str = "auto"
    """auto (from each part's material text), or PLA, PLA+, PETG, ABS."""
    layer_height: float = 0.2
    spacing: float = 6.0
    """Gap between parts on the bed, mm."""
    max_plate_hours: float = 24.0
    """Plates the slicer says would take longer are split in two (needs a slicer)."""


_JOB_KEYS = {f for f in JobSettings.__dataclass_fields__}
_PART_KEYS = {f for f in PartSettings.__dataclass_fields__}


def _part_settings(part: Part, job_overrides: dict[str, Any], own: dict[str, Any]) -> PartSettings:
    merged: dict[str, Any] = {}
    for src in (part.print_settings or {}, {k: v for k, v in job_overrides.items() if k in _PART_KEYS}, own or {}):
        unknown = set(src) - _PART_KEYS
        if unknown:
            raise ValueError(f"Unknown print settings {sorted(unknown)} for {part.name}. Known: {sorted(_PART_KEYS)}")
        merged.update(src)
    ps = PartSettings(**merged)
    if ps.orientation != "auto" and ps.orientation not in ORIENTATIONS:
        raise ValueError(f"orientation for {part.name} must be auto or one of {ORIENTATIONS}")
    if ps.supports not in ("auto", "on", "off"):
        raise ValueError(f"supports for {part.name} must be auto, on or off")
    ps.infill = float(ps.infill)
    ps.walls = int(ps.walls)
    ps.copies = max(0, int(ps.copies))
    if ps.brim != "auto":
        ps.brim = float(ps.brim)
    return ps


# --------------------------------------------------------------------------------------
# Which parts get printed
# --------------------------------------------------------------------------------------

_NOT_PRINTED = re.compile(
    r"^\s*buy\b|aluminium|aluminum|steel|brass|wood|ply\b|plywood|mdf|acrylic|fabric|filament cut|dowel|"
    r"\bpins?:|\bscrews?\b|\bbolts?\b|\bmagnets?\b",
    re.I,
)


def is_printable(part: Part) -> tuple[bool, str]:
    """(printed?, reason). `Part.printable` wins; otherwise guess from the material text."""
    if part.printable is not None:
        return part.printable, "set on the part"
    mat = part.material or ""
    m = _NOT_PRINTED.search(mat)
    if m and not re.search(r"\bprint", mat[: m.start()] if m.start() else "", re.I) and not re.match(r"\s*print", mat, re.I):
        return False, f"material is {mat!r}"
    return True, "printed part" if mat else "no material given, assumed printed"


def filament_for(part: Part) -> str:
    mat = (part.material or "").upper()
    for name in ("PETG", "ABS", "PLA+", "PLA"):
        if name in mat:
            return name
    if "PET" in mat:
        return "PETG"
    return DEFAULT_FILAMENT


# --------------------------------------------------------------------------------------
# Orientation
# --------------------------------------------------------------------------------------

OVERHANG_DEG = 45.0  # surfaces flatter than this (from horizontal), facing down, need support
HOLE_RADIUS = 5.0  # horizontal holes up to this radius print fine without support
BRIDGE_WIDTH = 8.0  # flat ceilings up to this wide bridge without support
SUPPORT_AREA = 100.0  # mm² of real overhang before "auto" turns supports on


@dataclass
class _Mesh:
    verts: np.ndarray  # (n, 3)
    tris: np.ndarray  # (m, 3) int
    face_of_tri: np.ndarray  # (m,) which BREP face each triangle came from
    face_kind: list[str]  # "plane", "small_cylinder" or "other"


def _cylinder_radius(face) -> float | None:
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface

        return BRepAdaptor_Surface(face.wrapped).Cylinder().Radius()
    except Exception:
        return None


def _mesh(part: Part, tolerance: float = 0.05, angular: float = 0.2) -> _Mesh:
    verts, tris, face_ids, kinds = [], [], [], []
    offset = 0
    for fi, face in enumerate(part.shape.faces()):
        gt = face.geom_type.name
        if gt == "PLANE":
            kinds.append("plane")
        elif gt == "CYLINDER" and (r := _cylinder_radius(face)) is not None and r <= HOLE_RADIUS:
            kinds.append("small_cylinder")
        else:
            kinds.append("other")
        vs, ts = face.tessellate(tolerance, angular)
        if not ts:
            continue
        verts.extend((v.X, v.Y, v.Z) for v in vs)
        tris.extend((a + offset, b + offset, c + offset) for a, b, c in ts)
        face_ids.extend([fi] * len(ts))
        offset += len(vs)
    return _Mesh(np.array(verts, float), np.array(tris, int), np.array(face_ids, int), kinds)


@dataclass
class Orientation:
    side: str
    yaw: float  # degrees about Z after laying the part down (0 or 45)
    size: tuple[float, float, float]  # footprint x, y and height after rotation
    overhang_mm2: float
    contact_mm2: float
    score: float
    rotation: np.ndarray = field(repr=False, default_factory=lambda: np.eye(3))
    straight_footprint: tuple[float, float] = (0.0, 0.0)
    """Footprint before any 45° turn."""

    @property
    def diagonal(self) -> bool:
        return self.yaw != 0


def _evaluate(mesh: _Mesh, side: str, printer: Printer) -> Orientation | None:
    R = _DOWN[side]
    v = mesh.verts @ R.T
    lo, hi = v.min(axis=0), v.max(axis=0)
    size = hi - lo
    if size[2] > printer.height + 1e-6:
        return None
    usable = np.array(printer.bed) - 2 * printer.margin
    yaw = 0.0
    sx, sy = float(size[0]), float(size[1])
    if not ((sx <= usable[0] and sy <= usable[1]) or (sy <= usable[0] and sx <= usable[1])):
        # Too long to lie straight: try it across the bed's diagonal.
        d = (sx + sy) / math.sqrt(2)
        if d > min(usable):
            return None
        yaw = 45.0
        R = _rz(45 if sx >= sy else -45) @ R
        v = mesh.verts @ R.T
        lo, hi = v.min(axis=0), v.max(axis=0)
        size = hi - lo

    a, b, c = v[mesh.tris[:, 0]], v[mesh.tris[:, 1]], v[mesh.tris[:, 2]]
    cross = np.cross(b - a, c - a)
    area = np.linalg.norm(cross, axis=1) / 2
    with np.errstate(invalid="ignore", divide="ignore"):
        nz = np.where(area > 0, cross[:, 2] / (2 * area), 0.0)
    tri_zmax = np.maximum(np.maximum(a[:, 2], b[:, 2]), c[:, 2])
    on_bed = tri_zmax < lo[2] + 0.05
    contact = float(area[on_bed & (nz < -0.99)].sum())

    down = (nz < -math.sin(math.radians(OVERHANG_DEG))) & ~on_bed
    overhang = 0.0
    for fi in np.unique(mesh.face_of_tri[down]):
        kind = mesh.face_kind[fi]
        if kind == "small_cylinder":
            continue  # pin and screw holes
        sel = down & (mesh.face_of_tri == fi)
        if kind == "plane":
            pts = np.concatenate([a[sel], b[sel], c[sel]])
            span = pts.max(axis=0) - pts.min(axis=0)
            if min(span[0], span[1]) <= BRIDGE_WIDTH:
                continue  # a short bridge
        overhang += float(area[sel].sum())

    h = float(size[2])
    narrow = max(1.0, float(min(size[0], size[1])))
    tall = max(0.0, h / narrow - 3.0)  # tall and thin wobbles at speed
    score = overhang + 0.3 * h + 40.0 * tall - 0.02 * contact + (60.0 if yaw else 0.0)
    return Orientation(side, yaw, (float(size[0]), float(size[1]), h), round(overhang, 1), round(contact, 1),
                       round(score, 1), R, (sx, sy))


def choose_orientation(part: Part, printer: Printer, wanted: str = "auto") -> tuple[Orientation | None, list[Orientation]]:
    mesh = _mesh(part)
    options = [o for s in ORIENTATIONS if (o := _evaluate(mesh, s, printer))]
    if wanted != "auto":
        pick = next((o for o in options if o.side == wanted), None)
        return pick, options
    if not options:
        return None, options
    # Ties go to the side listed first (as modelled).
    return min(options, key=lambda o: o.score), options


# --------------------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------------------


@dataclass
class Piece:
    name: str  # part name, with "#2" etc. for extra copies
    part: str
    settings: PartSettings
    orientation: Orientation
    supports: bool
    brim: float
    filament: str
    reasons: list[str]
    position: tuple[float, float] = (0.0, 0.0)  # footprint centre on the bed
    rotated_90: bool = False
    plate: int = 0

    def footprint(self) -> tuple[float, float]:
        x, y, _ = self.orientation.size
        return (y, x) if self.rotated_90 else (x, y)

    def to_dict(self) -> dict[str, Any]:
        o = self.orientation
        return {
            "name": self.name,
            "part": self.part,
            "plate": self.plate,
            "on_bed": o.side,
            "diagonal": o.diagonal,
            **({"strip_mm": [round(v, 1) for v in sorted(o.straight_footprint, reverse=True)]} if o.diagonal else {}),
            "size_mm": [round(s, 1) for s in (*self.footprint(), o.size[2])],
            "position_mm": [round(p, 1) for p in self.position],
            "supports": self.supports,
            "brim_mm": self.brim,
            "infill_pct": self.settings.infill,
            "walls": self.settings.walls,
            "filament": self.filament,
            "overhang_mm2": o.overhang_mm2,
            "why": "; ".join(self.reasons),
        }


@dataclass
class Plate:
    number: int
    filament: str
    pieces: list[Piece] = field(default_factory=list)
    diagonal: bool = False


@dataclass
class PrintPlan:
    design: str
    printer: Printer
    job: JobSettings
    pieces: list[Piece]
    plates: list[Plate]
    skipped: list[dict[str, str]]
    too_big: list[dict[str, Any]]

    def summary(self) -> dict[str, Any]:
        return {
            "design": self.design,
            "printer": self.printer.name,
            "job": asdict(self.job),
            "plates": [
                {"plate": p.number, "filament": p.filament, "parts": [x.name for x in p.pieces]} for p in self.plates
            ],
            "pieces": [p.to_dict() for p in self.pieces],
            "not_printed": self.skipped,
            "too_big": self.too_big,
        }


def plan_print(
    design: Design,
    settings: dict[str, Any] | None = None,
    part_settings: dict[str, dict[str, Any]] | None = None,
) -> PrintPlan:
    """Choose orientation and settings for every printable part and arrange them on plates.

    `settings`: job settings (printer, filament, layer_height, spacing) and/or
    part settings applied to every part (infill, walls, supports, brim, orientation).
    `part_settings`: {part name: {setting: value}} for individual parts.
    """
    settings = dict(settings or {})
    part_settings = dict(part_settings or {})
    unknown = set(settings) - _JOB_KEYS - _PART_KEYS
    if unknown:
        raise ValueError(f"Unknown settings {sorted(unknown)}. Job: {sorted(_JOB_KEYS)}; per part: {sorted(_PART_KEYS)}")
    names = {p.name for p in design.parts}
    missing = set(part_settings) - names
    if missing:
        raise ValueError(f"part_settings names parts that don't exist: {sorted(missing)}")
    job = JobSettings(**{k: v for k, v in settings.items() if k in _JOB_KEYS})
    if job.printer not in PRINTERS:
        raise ValueError(f"Unknown printer {job.printer!r}. Known: {sorted(PRINTERS)}")
    if job.filament != "auto" and job.filament not in FILAMENTS:
        raise ValueError(f"Unknown filament {job.filament!r}. Known: auto, {', '.join(FILAMENTS)}")
    printer = PRINTERS[job.printer]

    pieces: list[Piece] = []
    skipped: list[dict[str, str]] = []
    too_big: list[dict[str, Any]] = []
    for part in design.parts:
        printable, why = is_printable(part)
        if part.name in part_settings or part.print_settings:
            printable = True if part.printable is None else printable
        if not printable:
            skipped.append({"part": part.name, "why": why})
            continue
        ps = _part_settings(part, settings, part_settings.get(part.name, {}))
        if ps.copies == 0:
            skipped.append({"part": part.name, "why": "copies = 0"})
            continue
        orient, options = choose_orientation(part, printer, ps.orientation)
        if orient is None:
            bb = part.shape.bounding_box()
            too_big.append({
                "part": part.name,
                "size_mm": [round(bb.size.X, 1), round(bb.size.Y, 1), round(bb.size.Z, 1)],
                "why": (f"doesn't fit the {printer.name} ({printer.bed[0]:g} x {printer.bed[1]:g} x {printer.height:g} mm)"
                        + ("" if ps.orientation == "auto" else f" lying on its {ps.orientation}")
                        + ". Split it into pieces, or try another orientation."),
            })
            continue
        reasons = []
        if ps.orientation == "auto":
            reasons.append(f"on its {orient.side}" + (" across the diagonal (too long to lie straight)" if orient.diagonal else "")
                           + (f": {orient.overhang_mm2:.0f} mm² of overhang" if orient.overhang_mm2 else ": no overhangs"))
        else:
            reasons.append(f"on its {orient.side} (you chose it)")
        if ps.supports == "auto":
            supports = orient.overhang_mm2 > SUPPORT_AREA
            reasons.append("supports on (overhangs left)" if supports else "no supports needed")
        else:
            supports = ps.supports == "on"
        h = orient.size[2]
        narrow = min(orient.size[0], orient.size[1])
        if ps.brim == "auto":
            brim = 5.0 if (h > 4 * narrow or orient.contact_mm2 < 300) else 0.0
            if brim:
                reasons.append("5 mm brim (tall or small footprint)")
        else:
            brim = ps.brim
        fil = job.filament if job.filament != "auto" else filament_for(part)
        for k in range(ps.copies):
            pieces.append(Piece(part.name if k == 0 else f"{part.name}#{k + 1}", part.name, ps, orient,
                                supports, brim, fil, reasons))

    plates = _arrange(pieces, printer, job.spacing)
    return PrintPlan(design.name, printer, job, pieces, plates, skipped, too_big)


# --------------------------------------------------------------------------------------
# Arrangement
# --------------------------------------------------------------------------------------


def _arrange(pieces: list[Piece], printer: Printer, spacing: float) -> list[Plate]:
    """Pack pieces onto as few plates as possible, one filament per plate.

    Straight pieces go on shelves (rows), rotating 90° when that fits better.
    Pieces too long to lie straight lie side by side across the diagonal.
    """
    plates: list[Plate] = []
    usable_x = printer.bed[0] - 2 * printer.margin
    usable_y = printer.bed[1] - 2 * printer.margin
    for fil in sorted({p.filament for p in pieces}):
        group = [p for p in pieces if p.filament == fil]
        straight = [p for p in group if not p.orientation.diagonal]
        diagonal = [p for p in group if p.orientation.diagonal]

        # ---- shelves ----
        # Lay each piece long side along X, tallest-footprint first.
        for p in straight:
            x, y, _ = p.orientation.size
            p.rotated_90 = y > x and y + 2 * p.brim <= usable_x
        straight.sort(key=lambda p: (-_fp(p)[1], -_fp(p)[0]))
        open_plates: list[dict[str, Any]] = []  # {"plate", "shelves": [[y0, height, x_used]], "y_used"}
        for p in straight:
            w, d = _fp(p)
            if w > usable_x:  # only fits turned
                p.rotated_90 = not p.rotated_90
                w, d = _fp(p)
            placed = False
            for op in open_plates:
                for shelf in op["shelves"]:
                    y0, sh, xu = shelf
                    if d <= sh + 1e-6 and xu + w <= usable_x + 1e-6:
                        p.position = (printer.margin + xu + w / 2, printer.margin + y0 + d / 2)
                        shelf[2] = xu + w + spacing
                        op["plate"].pieces.append(p)
                        placed = True
                        break
                if placed:
                    break
                if op["y_used"] + d <= usable_y + 1e-6:
                    y0 = op["y_used"]
                    op["shelves"].append([y0, d, w + spacing])
                    op["y_used"] = y0 + d + spacing
                    p.position = (printer.margin + w / 2, printer.margin + y0 + d / 2)
                    op["plate"].pieces.append(p)
                    placed = True
                    break
            if not placed:
                plate = Plate(0, fil)
                plates.append(plate)
                p.position = (printer.margin + w / 2, printer.margin + d / 2)
                plate.pieces.append(p)
                open_plates.append({"plate": plate, "shelves": [[0.0, d, w + spacing]], "y_used": d + spacing})

        # ---- diagonal strips ----
        # A strip at perpendicular distance t from the bed's main diagonal has
        # room for a piece of length L while |t| + w/2 <= (S*sqrt2 - L) / 2.
        diagonal.sort(key=lambda p: -max(p.orientation.size[:2]))
        S = min(usable_x, usable_y)
        cx, cy = printer.bed[0] / 2, printer.bed[1] / 2
        current: Plate | None = None
        band: list[float] = []  # [lowest t used, highest t used]
        for p in diagonal:
            L, w = _strip_dims(p)
            if current is not None:
                limit = (S * math.sqrt(2) - L) / 2
                hi_t = band[1] + spacing + w / 2
                lo_t = band[0] - spacing - w / 2
                if hi_t + w / 2 <= limit:
                    t = hi_t
                    band[1] = t + w / 2
                elif -lo_t + w / 2 <= limit:
                    t = lo_t
                    band[0] = t - w / 2
                else:
                    current = None
            if current is None:
                current = Plate(0, fil, diagonal=True)
                plates.append(current)
                t = 0.0
                band = [-w / 2, w / 2]
            # The strip's centre line runs along (1, 1)/sqrt2; offset perpendicular along (1, -1)/sqrt2.
            p.position = (cx + t / math.sqrt(2), cy - t / math.sqrt(2))
            current.pieces.append(p)

    for plate in plates:
        if not plate.diagonal:
            _centre(plate, printer)
    for i, plate in enumerate(plates, start=1):
        plate.number = i
        for p in plate.pieces:
            p.plate = i
    return plates


def _centre(plate: Plate, printer: Printer) -> None:
    """Move a plate's pieces together so their group sits in the middle of the bed."""
    lo = [min(p.position[k] - _fp(p)[k] / 2 for p in plate.pieces) for k in (0, 1)]
    hi = [max(p.position[k] + _fp(p)[k] / 2 for p in plate.pieces) for k in (0, 1)]
    dx = printer.bed[0] / 2 - (lo[0] + hi[0]) / 2
    dy = printer.bed[1] / 2 - (lo[1] + hi[1]) / 2
    for p in plate.pieces:
        p.position = (p.position[0] + dx, p.position[1] + dy)


def _fp(p: Piece) -> tuple[float, float]:
    """Footprint including the brim."""
    w, d = p.footprint()
    return w + 2 * p.brim, d + 2 * p.brim


def _strip_dims(p: Piece) -> tuple[float, float]:
    """Length and width (with brim) of a diagonal piece, measured along and across its strip."""
    L, w = p.orientation.straight_footprint
    return max(L, w) + 2 * p.brim, min(L, w) + 2 * p.brim


# --------------------------------------------------------------------------------------
# Output: PrusaSlicer project (.3mf) per plate, then G-code
# --------------------------------------------------------------------------------------


def read_profile(printer: Printer) -> dict[str, str]:
    """The printer's .ini as an ordered dict of raw (still escaped) values."""
    out: dict[str, str] = {}
    for line in (PRINTERS_DIR / printer.profile).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def plate_config(plan: PrintPlan, plate: Plate) -> dict[str, str]:
    """Full slicer config for one plate: printer profile + filament + job settings."""
    cfg = read_profile(plan.printer)
    for k, v in FILAMENTS[plate.filament].items():
        cfg[k] = str(v)
    cfg["filament_settings_id"] = f"Generic {plate.filament} (aicad)"
    cfg["print_settings_id"] = f"{plan.job.layer_height:g} mm (aicad)"
    lh = plan.job.layer_height
    cfg["layer_height"] = f"{lh:g}"
    cfg["first_layer_height"] = f"{min(0.2, max(0.14, lh * 0.7)):.2f}"
    return cfg


def _object_overrides(piece: Piece) -> dict[str, str]:
    s = piece.settings
    out = {
        "fill_density": f"{s.infill:g}%",
        "perimeters": str(s.walls),
        "support_material": "1" if piece.supports else "0",
        "support_material_auto": "1",
        "support_material_threshold": f"{int(90 - OVERHANG_DEG)}",
        "brim_width": f"{piece.brim:g}",
    }
    return out


def _placed_mesh(piece: Piece, design: Design) -> tuple[np.ndarray, np.ndarray]:
    """Vertices rotated into print orientation, centred on the footprint, sitting on z = 0."""
    part = design.part(piece.part)
    verts, tris = part.shape.tessellate(0.02, 0.1)
    v = np.array([(p.X, p.Y, p.Z) for p in verts], float)
    R = piece.orientation.rotation
    if piece.rotated_90:
        R = _rz(90) @ R
    v = v @ R.T
    lo, hi = v.min(axis=0), v.max(axis=0)
    v -= np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    return v, np.array(tris, int)


def write_3mf(plan: PrintPlan, plate: Plate, design: Design, path: Path) -> None:
    """A PrusaSlicer-flavoured 3MF: objects placed on the bed, per-object settings, full config."""
    objects_xml, items_xml, model_cfg = [], [], []
    for oid, piece in enumerate(plate.pieces, start=1):
        v, t = _placed_mesh(piece, design)
        vx = "".join(f'<vertex x="{a:.5f}" y="{b:.5f}" z="{c:.5f}"/>' for a, b, c in v)
        tx = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in t)
        objects_xml.append(f'<object id="{oid}" type="model"><mesh><vertices>{vx}</vertices>'
                           f'<triangles>{tx}</triangles></mesh></object>')
        x, y = piece.position
        items_xml.append(f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 {x:.4f} {y:.4f} 0" printable="1"/>')
        meta = [f'<metadata type="object" key="name" value="{escape(piece.name)}"/>']
        meta += [f'<metadata type="object" key="{k}" value="{escape(v_)}"/>' for k, v_ in _object_overrides(piece).items()]
        model_cfg.append(
            f' <object id="{oid}" instances_count="1">\n  ' + "\n  ".join(meta) + "\n"
            f'  <volume firstid="0" lastid="{len(t) - 1}">\n'
            f'   <metadata type="volume" key="name" value="{escape(piece.name)}"/>\n'
            f'   <metadata type="volume" key="volume_type" value="ModelPart"/>\n'
            f'   <metadata type="volume" key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
            '  </volume>\n </object>'
        )
    title = f"{plan.design} plate {plate.number}"
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">\n'
        ' <metadata name="slic3rpe:Version3mf">1</metadata>\n'
        f' <metadata name="Title">{escape(title)}</metadata>\n'
        ' <metadata name="Application">AI CAD (aicad)</metadata>\n'
        f' <resources>{"".join(objects_xml)}</resources>\n'
        f' <build>{"".join(items_xml)}</build>\n'
        '</model>\n'
    )
    cfg = plate_config(plan, plate)
    config_text = "; generated by AI CAD for PrusaSlicer-compatible slicers\n" + "".join(
        f"; {k} = {v}\n" for k, v in cfg.items()
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                    '<Default Extension="config" ContentType="text/plain"/>'
                    '</Types>')
        zf.writestr("_rels/.rels",
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
                    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        zf.writestr("3D/3dmodel.model", model)
        zf.writestr("Metadata/Slic3r_PE.config", config_text)
        zf.writestr("Metadata/Slic3r_PE_model.config",
                    '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(model_cfg) + "\n</config>\n")


# ---- finding a slicer ----

_SLICER_NAMES = ("prusa-slicer", "PrusaSlicer", "prusaslicer", "superslicer", "SuperSlicer")
_SLICER_APPS = (
    "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
    "/Applications/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
    "/Applications/SuperSlicer.app/Contents/MacOS/SuperSlicer",
    "~/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
    r"C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe",
)


def find_slicer() -> str | None:
    """A PrusaSlicer-compatible command line slicer: $AICAD_SLICER, then PATH, then the usual app folders."""
    env = os.environ.get("AICAD_SLICER")
    if env:
        return env if Path(env).expanduser().exists() or shutil.which(env) else None
    for name in _SLICER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for app in _SLICER_APPS:
        p = Path(app).expanduser()
        if p.exists():
            return str(p)
    return None


_STAT_PATTERNS = {
    "print_time": re.compile(r"^; estimated printing time \(normal mode\) = (.+)$", re.M),
    "filament_g": re.compile(r"^; (?:total )?filament used \[g\] = ([\d.]+)", re.M),
    "filament_m": re.compile(r"^; filament used \[mm\] = ([\d.]+)", re.M),
}


def gcode_stats(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if m := _STAT_PATTERNS["print_time"].search(text):
        out["print_time"] = m.group(1).strip()
    if m := _STAT_PATTERNS["filament_g"].search(text):
        out["filament_g"] = round(float(m.group(1)), 1)
    if m := _STAT_PATTERNS["filament_m"].search(text):
        out["filament_m"] = round(float(m.group(1)) / 1000, 2)
    return out


def slice_3mf(slicer: str, project: Path, config: dict[str, str], out: Path, timeout: float = 900) -> dict[str, Any]:
    """Run the slicer's command line on one plate. Returns stats, or the error it printed."""
    with tempfile.TemporaryDirectory() as tmp:
        ini = Path(tmp) / "plate.ini"
        ini.write_text("".join(f"{k} = {v}\n" for k, v in config.items()))
        cmd = [slicer, "--export-gcode", "--dont-arrange", "--load", str(ini), "--output", str(out), str(project)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"error": f"slicer timed out after {timeout:.0f} s"}
    if proc.returncode != 0 or not out.exists():
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        return {"error": "slicer failed: " + " | ".join(msg[-5:])}
    return gcode_stats(out.read_text(errors="replace"))


# ---- the whole job ----


def _hours(print_time: str) -> float:
    """'1d 17h 35m 54s' -> 41.6"""
    units = {"d": 24.0, "h": 1.0, "m": 1 / 60, "s": 1 / 3600}
    return sum(float(n) * units[u] for n, u in re.findall(r"(\d+)([dhms])", print_time))


def _split(plate: Plate, plan: PrintPlan) -> list[Plate]:
    """Share a plate's pieces between two new plates, balancing printed volume."""
    halves: list[list[Piece]] = [[], []]
    vols = [0.0, 0.0]
    for p in sorted(plate.pieces, key=lambda p: -p.orientation.size[2] * p.footprint()[0] * p.footprint()[1]):
        k = 0 if vols[0] <= vols[1] else 1
        halves[k].append(p)
        vols[k] += p.orientation.size[2] * p.footprint()[0] * p.footprint()[1]
    return [pl for half in halves if half for pl in _arrange(half, plan.printer, plan.job.spacing)]


def write_print_job(plan: PrintPlan, design: Design, out_dir: Path, slice: bool = True) -> dict[str, Any]:
    """Write <design>-plate_N.3mf (+ .gcode when a slicer is available), plan.json and PRINT-LIST.md.

    When a sliced plate would take longer than `max_plate_hours`, its pieces are
    shared between two plates and sliced again, so no single print runs for days.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in [*out_dir.glob("*-plate_*.3mf"), *out_dir.glob("*-plate_*.gcode")]:
        old.unlink()
    slicer = find_slicer() if slice else None
    results: list[tuple[Plate, dict[str, Any]]] = []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        queue = list(plan.plates)
        n = 0
        while queue:
            plate = queue.pop(0)
            n += 1
            project = work / f"{n}.3mf"
            write_3mf(plan, plate, design, project)
            result: dict[str, Any] = {"_3mf": project}
            if slicer:
                gcode = work / f"{n}.gcode"
                result.update(slice_3mf(slicer, project, plate_config(plan, plate), gcode))
                too_long = "print_time" in result and _hours(result["print_time"]) > plan.job.max_plate_hours
                if too_long and len(plate.pieces) > 1:
                    queue[:0] = _split(plate, plan)
                    continue
                if "error" not in result:
                    result["_gcode"] = gcode
            results.append((plate, result))

        plan.plates = [pl for pl, _ in results]
        plates_out = []
        for number, (plate, result) in enumerate(results, start=1):
            plate.number = number
            for p in plate.pieces:
                p.plate = number
            stem = f"{plan.design}-plate_{number}"
            entry: dict[str, Any] = {
                "plate": number,
                "filament": plate.filament,
                "parts": [p.name for p in plate.pieces],
                "project_3mf": str(out_dir / f"{stem}.3mf"),
            }
            shutil.move(result["_3mf"], entry["project_3mf"])
            if "_gcode" in result:
                entry["gcode"] = str(out_dir / f"{stem}.gcode")
                shutil.move(result["_gcode"], entry["gcode"])
            if "error" in result:
                entry["slice_error"] = result["error"]
            entry.update({k: v for k, v in result.items() if k in ("print_time", "filament_g", "filament_m")})
            if "print_time" in entry and _hours(entry["print_time"]) > plan.job.max_plate_hours:
                entry["note"] = f"one piece alone takes longer than {plan.job.max_plate_hours:g} h"
            plates_out.append(entry)

    summary = plan.summary()
    summary["plates"] = plates_out
    summary["slicer"] = slicer or None
    if plates_out and all("filament_g" in p for p in plates_out):
        summary["total"] = {
            "filament_g": round(sum(p["filament_g"] for p in plates_out), 1),
            "print_hours": round(sum(_hours(p["print_time"]) for p in plates_out), 1),
        }
    if slice and not slicer:
        summary["slicer_note"] = (
            "No PrusaSlicer found, so no G-code yet. Open each .3mf in AnkerMake Studio and press Slice, "
            "or install PrusaSlicer (or set AICAD_SLICER to its command line binary) and run this again."
        )
    (out_dir / "plan.json").write_text(json.dumps(summary, indent=2))
    (out_dir / "PRINT-LIST.md").write_text(print_list_markdown(summary))
    summary["out_dir"] = str(out_dir)
    return summary


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def print_list_markdown(summary: dict[str, Any]) -> str:
    job = summary["job"]
    lines = [
        f"# {summary['design']}: print list ({summary['printer']})",
        "",
        f"{_n(len(summary['pieces']), 'piece')} on {_n(len(summary['plates']), 'plate')}, "
        f"{job['layer_height']:g} mm layers."
        + (f" About {summary['total']['print_hours']:g} hours and {summary['total']['filament_g']:g} g of filament in all."
           if summary.get("total") else ""),
        "",
    ]
    by_name = {p["name"]: p for p in summary["pieces"]}
    for plate in summary["plates"]:
        stats = []
        if plate.get("print_time"):
            stats.append(plate["print_time"])
        if plate.get("filament_g"):
            stats.append(f"{plate['filament_g']:g} g")
        head = f"## Plate {plate['plate']} ({plate['filament']}" + (", " + ", ".join(stats) if stats else "") + ")"
        lines += [head, "", f"File: `{Path(plate.get('gcode') or plate['project_3mf']).name}`", ""]
        if plate.get("slice_error"):
            lines += [f"Slicing failed: {plate['slice_error']}", ""]
        lines += ["| Part | On its | Size (mm) | Supports | Brim | Infill | Walls |", "|---|---|---|---|---|---|---|"]
        for name in plate["parts"]:
            p = by_name[name]
            size = " x ".join(f"{s:g}" for s in p["size_mm"])
            lines.append(
                f"| {name} | {p['on_bed']}{' (diagonal)' if p['diagonal'] else ''} | {size} | "
                f"{'yes' if p['supports'] else 'no'} | {p['brim_mm']:g} mm | {p['infill_pct']:g}% | {p['walls']} |"
            )
        lines.append("")
    if summary.get("too_big"):
        lines += ["## Too big for the bed", ""] + [f"- {t['part']}: {t['why']}" for t in summary["too_big"]] + [""]
    if summary.get("not_printed"):
        lines += ["## Not printed", ""] + [f"- {s['part']}: {s['why']}" for s in summary["not_printed"]] + [""]
    if summary.get("slicer_note"):
        lines += [summary["slicer_note"], ""]
    return "\n".join(lines)


def job_zip_bytes(out_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(out_dir.iterdir()):
            if f.is_file():
                zf.write(f, f.name)
    return buf.getvalue()
