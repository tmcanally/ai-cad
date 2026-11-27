"""The data model every AI CAD design returns.

A design module builds its geometry with build123d and returns a `Design`:
a list of named `Part`s (each with a colour and an explode offset) plus
`Motion`s that say how parts move. Motions are read straight from build123d
joints, so the viewer animates exactly what the CAD model defines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from build123d import Axis, Edge, GeomType, RevoluteJoint, Shape


@dataclass
class Param:
    """A user-tunable number on a design, shown as an input in the viewer."""

    default: float
    min: float | None = None
    max: float | None = None
    unit: str = "mm"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "unit": self.unit,
            "description": self.description,
        }


@dataclass
class Part:
    """One physical piece. `shape` is placed where it sits in the assembled design."""

    name: str
    shape: Shape
    color: str = "#9aa7b8"
    explode: tuple[float, float, float] = (0.0, 0.0, 0.0)
    """Offset in mm applied when the viewer's explode slider is at 100%."""
    material: str = ""
    """Free text for now, e.g. "PLA" or "6 mm birch ply"."""


@dataclass
class Motion:
    """A degree of freedom the viewer can animate (currently revolute only)."""

    name: str
    parts: list[str]
    origin: tuple[float, float, float]
    direction: tuple[float, float, float]
    range: tuple[float, float]
    kind: str = "revolute"

    @classmethod
    def from_revolute_joint(
        cls, name: str, joint: RevoluteJoint, parts: list[str]
    ) -> "Motion":
        """Read the world-space hinge axis and angle limits from a build123d joint.

        Angles follow the right-hand rule about `direction`, the same
        convention build123d uses in `RevoluteJoint.connect_to(angle=...)`.
        """
        axis: Axis = joint.relative_axis.located(joint.parent.location)
        o, d = axis.position, axis.direction
        return cls(
            name=name,
            parts=parts,
            origin=(o.X, o.Y, o.Z),
            direction=(d.X, d.Y, d.Z),
            range=tuple(joint.angular_range),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "parts": self.parts,
            "origin": list(self.origin),
            "direction": list(self.direction),
            "range": list(self.range),
        }


@dataclass
class Design:
    name: str
    parts: list[Part]
    motions: list[Motion] = field(default_factory=list)
    notes: str = ""

    def part(self, name: str) -> Part:
        for p in self.parts:
            if p.name == name:
                return p
        raise KeyError(f"No part named {name!r}. Parts: {[p.name for p in self.parts]}")

    def summary(self) -> dict[str, Any]:
        """Small, text-friendly description (used by the MCP server)."""
        parts = []
        for p in self.parts:
            bb = p.shape.bounding_box()
            parts.append(
                {
                    "name": p.name,
                    "material": p.material,
                    "volume_mm3": round(p.shape.volume, 1),
                    "size_mm": [round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)],
                    "is_valid": p.shape.is_valid,
                }
            )
        return {
            "name": self.name,
            "parts": parts,
            "motions": [m.to_dict() for m in self.motions],
            "notes": self.notes,
        }

    def to_viewer_json(self, tolerance: float = 0.05, angular_tolerance: float = 0.2) -> dict[str, Any]:
        """Tessellate every part into the mesh + edge format the web viewer reads."""
        out_parts = []
        lo = [float("inf")] * 3
        hi = [float("-inf")] * 3
        for p in self.parts:
            verts, tris = p.shape.tessellate(tolerance, angular_tolerance)
            positions = [round(c, 4) for v in verts for c in (v.X, v.Y, v.Z)]
            indices = [i for t in tris for i in t]
            bb = p.shape.bounding_box()
            for k, (a, b) in enumerate(((bb.min.X, bb.max.X), (bb.min.Y, bb.max.Y), (bb.min.Z, bb.max.Z))):
                lo[k] = min(lo[k], a)
                hi[k] = max(hi[k], b)
            out_parts.append(
                {
                    "name": p.name,
                    "color": p.color,
                    "material": p.material,
                    "explode": list(p.explode),
                    "mesh": {"positions": positions, "indices": indices},
                    "edges": _edge_polylines(p.shape),
                }
            )
        return {
            "name": self.name,
            "notes": self.notes,
            "bbox": {"min": lo, "max": hi},
            "parts": out_parts,
            "motions": [m.to_dict() for m in self.motions],
        }


def _edge_polylines(shape: Shape) -> list[list[float]]:
    """CAD edges as flat [x0,y0,z0,x1,y1,z1,...] polylines for crisp outlines."""
    lines = []
    for e in shape.edges():
        e: Edge
        n = 2 if e.geom_type == GeomType.LINE else 33
        pts = [e.position_at(i / (n - 1)) for i in range(n)]
        lines.append([round(c, 4) for v in pts for c in (v.X, v.Y, v.Z)])
    return lines
