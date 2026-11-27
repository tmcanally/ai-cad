"""Cordless top-down/bottom-up Roman shade with no visible cords.

How it works
------------
Two U-shaped side channels run from the sill to the headrail inside the
window frame. The middle rail (the top of the fabric) and the bottom rail
each ride in both channels on end carriers with friction pads. Each carrier
hangs from a constant-force spring (a coiled steel tape) housed in the
headrail above its channel, and the tape runs down inside the channel, so
nothing is visible from the room. The springs carry most of each rail's
weight and the friction pads hold it wherever it is left, so you just push
or pull a rail by its handle.

The fabric hangs from the middle rail and is fixed to the bottom rail.
Battens sewn into pockets on the back of the fabric have pins at both ends
that slide in the same channels. That keeps them level and replaces the lift
cords: when the bottom rail rises it picks up each batten in turn, and the
fabric between battens folds forward into the usual Roman shade pleats.

Coordinates: X across the window, Z up from the sill, -Y towards the room.
The two "position" parameters (top_drop and bottom_raise) are what the
Motion sliders sweep. The build works out every batten and fold from them.
"""

from __future__ import annotations

import math

from build123d import Align, Axis, Box, Compound, Cylinder, Face, Line, Pos, Rot, Spline, Wire, extrude, fillet

from aicad.design import Design, Motion, Param, Part

TITLE = "Roman shade, top-down/bottom-up"
DESCRIPTION = "Cordless TDBU Roman shade: rails ride in side channels on hidden constant-force springs."

PARAMS = {
    "window_width": Param(900, 400, 2400, description="Inside width of the window frame"),
    "window_height": Param(1200, 500, 2800, description="Inside height of the window frame"),
    "headrail_height": Param(45, 30, 100, description="Headrail height (houses the springs)"),
    "headrail_depth": Param(50, 35, 120, description="Headrail depth front to back"),
    "channel_width": Param(22, 14, 50, description="Side channel width across the window"),
    "channel_depth": Param(30, 20, 60, description="Side channel depth front to back"),
    "channel_wall": Param(2, 1, 4, description="Side channel wall thickness"),
    "slot_width": Param(10, 4, 30, description="Opening in each channel that pins and carriers pass through"),
    "rail_height": Param(30, 15, 60, description="Middle and bottom rail height"),
    "rail_depth": Param(22, 12, 50, description="Middle and bottom rail depth"),
    "handle_length": Param(80, 0, 200, description="Pull handle length on each rail (0 = none)"),
    "fold_spacing": Param(180, 80, 400, description="Fabric length between battens"),
    "batten_size": Param(8, 4, 15, description="Batten thickness"),
    "fabric_thickness": Param(1.5, 0.5, 5, description="Fabric thickness"),
    "spring_diameter": Param(28, 12, 40, description="Constant-force spring coil diameter"),
    "tape_width": Param(8, 4, 20, description="Spring tape width"),
    "top_drop": Param(0, 0, 2000, description="Position: how far the top of the shade is lowered"),
    "bottom_raise": Param(0, 0, 2000, description="Position: how far the bottom of the shade is raised"),
}

C_MIN = (Align.CENTER, Align.CENTER, Align.MIN)


def build(
    window_width=900,
    window_height=1200,
    headrail_height=45,
    headrail_depth=50,
    channel_width=22,
    channel_depth=30,
    channel_wall=2,
    slot_width=10,
    rail_height=30,
    rail_depth=22,
    handle_length=80,
    fold_spacing=180,
    batten_size=8,
    fabric_thickness=1.5,
    spring_diameter=28,
    tape_width=8,
    top_drop=0,
    bottom_raise=0,
) -> Design:
    W, H = window_width, window_height
    cw, cd, wall = channel_width, channel_depth, channel_wall
    rh, rd, bt, ft = rail_height, rail_depth, batten_size, fabric_thickness
    top = H - headrail_height  # underside of the headrail
    inner_w = W - 2 * cw  # clear width between the channels
    chan_x = W / 2 - cw / 2  # channel centre lines

    # ---------------- fabric layout and the two positions ----------------
    fabric_len = top - 2 * rh  # fabric between the rails when the shade is fully closed
    n_folds = max(1, round(fabric_len / fold_spacing))
    pitch = fabric_len / n_folds
    n_battens = n_folds - 1
    stack = n_battens * bt + 2 * ft * n_folds  # height of everything stacked on the bottom rail

    top_drop = min(top_drop, top - 2 * rh - stack)
    mid_top = top - top_drop
    z0 = mid_top - rh  # fabric hangs from here
    bottom_raise = min(bottom_raise, z0 - stack - rh)
    z1 = bottom_raise + rh  # fabric fixed here, on top of the bottom rail

    # Battens hang from the middle rail at one fold spacing apart, unless the
    # bottom rail has come up far enough to be carrying them.
    anchors = [z0]
    for i in range(1, n_battens + 1):
        hanging = z0 - i * pitch
        stacked = z1 + (n_battens - i) * bt + bt / 2 + 2 * ft * (n_folds - i)
        anchors.append(max(hanging, stacked))
    anchors.append(z1)

    # ---------------- side channels ----------------
    def channel(side: int):
        body = Box(cw, cd, top, align=C_MIN)
        body -= Pos(0, 0, -1) * Box(cw - 2 * wall, cd - 2 * wall, top + 2, align=C_MIN)
        body -= Pos(-side * (cw / 2 - wall / 2), 0, -1) * Box(wall * 2, slot_width, top + 2, align=C_MIN)
        return Pos(side * chan_x, 0, 0) * body

    channels = channel(-1) + channel(1)

    # ---------------- headrail with spring housings ----------------
    head = Pos(0, 0, top) * Box(W, headrail_depth, headrail_height, align=C_MIN)
    head = fillet(head.edges().filter_by(Axis.X).group_by(Axis.Y)[0], min(6, headrail_height / 4))
    head -= Pos(0, 0, top - 1) * Box(W - 2 * wall, headrail_depth - 2 * wall, headrail_height - wall + 1, align=C_MIN)

    # Each channel has two springs, one per rail. A coil's axis runs across the
    # window; its tape leaves the coil tangentially and drops straight down the
    # channel. The middle rail's tape runs down the front of the channel and the
    # bottom rail's down the back, and the two coils sit side by side so they
    # fit in the headrail.
    inner_cw = cw - 2 * wall
    tape_y = {"middle": -(cd / 2 - wall - 3), "bottom": cd / 2 - wall - 3}
    tape_dx = {"middle": -min(tape_width / 2 + 1, inner_cw / 4), "bottom": min(tape_width / 2 + 1, inner_cw / 4)}
    coil_w = min(tape_width + 1, inner_cw / 2 - 0.5)
    spring_r = min(spring_diameter / 2, headrail_height / 2 - wall - 0.5, headrail_depth / 2 - wall - abs(tape_y["middle"]) - 0.5)
    coil_z = top + headrail_height / 2
    springs, tapes = [], []
    for side in (-1, 1):
        for rail, carrier_top in (("middle", mid_top), ("bottom", bottom_raise + rh)):
            x = side * (chan_x + tape_dx[rail])  # inboard for the middle rail, outboard for the bottom
            y = tape_y[rail]
            coil_y = y + spring_r if rail == "middle" else y - spring_r
            springs.append(Pos(x, coil_y, coil_z) * Rot(0, 90, 0) * Cylinder(spring_r, coil_w))
            tapes.append(Pos(x, y, carrier_top) * Box(min(tape_width, coil_w), 0.4, coil_z - carrier_top, align=C_MIN))

    # ---------------- rails with end carriers ----------------
    def rail(z_bottom: float, carrier_y: float, carrier_d: float):
        body = Pos(0, 0, z_bottom) * Box(inner_w, rd, rh, align=C_MIN)
        body = fillet(body.edges().filter_by(Axis.X).group_by(Axis.Y)[0], min(4, rh / 4))
        for side in (-1, 1):
            # Tongue through the slot, then a carrier block inside the channel with friction pads.
            body += Pos(side * (inner_w / 2 + wall), 0, z_bottom + rh / 2) * Box(wall * 2 + 2, slot_width - 1, rh * 0.6)
            body += Pos(side * chan_x, carrier_y, z_bottom) * Box(cw - 2 * wall - 1, carrier_d, rh, align=C_MIN)
        if handle_length > 0:
            body += Pos(0, -rd / 2 - 4, z_bottom + rh / 2) * Box(handle_length, 8, rh * 0.35)
        return body

    # Middle carrier stays in the front of the channel so the bottom rail's tape passes behind it.
    inner_d = cd - 2 * wall - 1
    middle = rail(z0, -inner_d * 0.2, inner_d * 0.55)
    bottom = rail(bottom_raise, 0, inner_d)

    # ---------------- battens with pins into the channels ----------------
    batten_y = ft + bt / 2  # just behind the fabric, inside its pocket
    battens = [
        Pos(0, batten_y, z) * Box(W - 2 * wall - 2, bt, bt) for z in anchors[1:-1]
    ]

    # ---------------- fabric: flat where taut, folded forward where slack ----------------
    folds = [_fabric_segment(a, b, pitch, ft, inner_w - 2) for a, b in zip(anchors[:-1], anchors[1:])]

    open_gap = (anchors[0] - anchors[-1]) > pitch * n_folds - 1
    return Design(
        name="roman_shade",
        parts=[
            Part("headrail", head, color="#d7dbe0", explode=(0, 0, headrail_height * 3), material="Aluminium or printed PETG"),
            Part("springs", Compound(springs + tapes), color="#8f99a6", explode=(0, 0, headrail_height * 3),
                 material="Constant-force springs (steel tape)"),
            Part("channels", channels, color="#c3c9d1", explode=(0, 0, 0), material="Aluminium or printed PETG"),
            Part("middle_rail", middle, color="#4f7cac", explode=(0, -rd * 6, 0), material="Aluminium + printed carriers"),
            Part("bottom_rail", bottom, color="#3d5f86", explode=(0, -rd * 6, 0), material="Aluminium + printed carriers"),
            Part("fabric", Compound(folds), color="#e8dcc4", explode=(0, -rd * 3, 0), material="Fabric"),
            Part("battens", Compound(battens) if battens else Box(1, 1, 1), color="#a0724a", explode=(0, rd * 4, 0),
                 material="6-8 mm wood or fibreglass rod"),
        ],
        motions=[
            Motion.from_param("lower_top", "top_drop", (0, top - 2 * rh - stack)),
            Motion.from_param("raise_bottom", "bottom_raise", (0, top - 2 * rh - stack)),
        ],
        notes=(
            f"{n_folds} folds of {pitch:.0f} mm, {n_battens} battens. "
            + ("Shade fully closed. " if open_gap and top_drop == 0 and bottom_raise == 0 else "")
            + "No lift cords: rails are carried by constant-force springs inside the channels and held by friction pads."
        ),
    )


def _fabric_segment(z_top: float, z_bot: float, length: float, t: float, width: float):
    """One panel of fabric between two anchors, keeping its true length.

    Taut: a flat sheet. A little slack: a half-sine bulge towards the room.
    Very slack (anchors stacked close together): a flattened loop, which is
    how a Roman shade pleat looks once the battens have stacked up.
    """
    drop = max(z_top - z_bot, 4 * t)
    steps = 24

    def sine(depth: float):
        return [(-depth * math.sin(math.pi * i / steps), z_top - drop * i / steps) for i in range(steps + 1)]

    if drop >= length - 0.5:
        pts = sine(0.0)
    elif drop >= 2 * length / math.pi:
        lo, hi = 0.0, length
        for _ in range(40):
            depth = (lo + hi) / 2
            pts = sine(depth)
            if sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) > length:
                hi = depth
            else:
                lo = depth
        pts = sine(lo)
    else:
        r = drop / 2
        reach = (length - math.pi * r) / 2  # straight run out and back
        zm = z_top - r
        run = [reach * i / 6 for i in range(6)]
        pts = [(-x, z_top) for x in run]
        pts += [(-reach - r * math.sin(math.pi * i / steps), zm + r * math.cos(math.pi * i / steps)) for i in range(steps + 1)]
        pts += [(-x, z_top - drop) for x in reversed(run)]

    # Thicken towards the inside of the bulge by offsetting along each point's normal.
    inner = []
    last = len(pts) - 1
    for i, (y, z) in enumerate(pts):
        (y0, z0), (y1, z1) = pts[max(0, i - 1)], pts[min(last, i + 1)]
        dy, dz = y1 - y0, z1 - z0
        n = math.hypot(dy, dz) or 1.0
        inner.append((y - dz / n * t, z + dy / n * t))
    # Smooth splines rather than a polygon, so the fabric reads as cloth, not facets.
    outer_pts = [(0, y, z) for y, z in pts]
    inner_pts = [(0, y, z) for y, z in inner]
    wire = Wire([
        Spline(*outer_pts),
        Line(outer_pts[-1], inner_pts[-1]),
        Spline(*inner_pts[::-1]),
        Line(inner_pts[0], outer_pts[0]),
    ])
    return Pos(-width / 2, 0, 0) * extrude(Face(wire), width, dir=(1, 0, 0))
