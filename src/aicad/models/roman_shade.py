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
Motorized version (motorized = 1)
---------------------------------
The springs and friction pads give way to two small geared stepper motors in
the headrail, one per rail. Each motor sits on its own cross shaft with a GT2
pulley above each channel, and a timing-belt loop runs down the outer half of
each channel to an idler at the sill. Each rail's carriers clamp one strand of
their belt, so both ends of a rail always move together and it stays level.
The middle rail's belts run in the front of the channels and the bottom
rail's in the back. A worm or high-ratio gearbox keeps the shade where it is
with the power off. A controller board (ESP32 + two TMC2209 drivers, which can
home without limit switches) sits on the back wall of the headrail. One power
lead goes into the headrail; nothing else shows.

Printing it (print_pieces = 1)
------------------------------
Every structural part is sized for a home 3D printer. The headrail, side
channels and rails are cut into pieces no longer than `max_piece_length`
(240 mm fits the AnkerMake M5's 235 x 235 x 250 mm when printed standing up,
which also means the channel and headrail profiles need no supports). Pieces
join with short lengths of 1.75 mm filament pushed into matching holes, so
assembly is: push pins in, push pieces together, screw the channels to the
window frame and the headrail to the head of the frame. The thicker wall on
the frame side of the channels and on the back of the headrail is there to
hold those pins. Fabric, battens, springs, motors and belts are bought parts.

The two "position" parameters (top_drop and bottom_raise) are what the
Motion sliders sweep. The build works out every batten and fold from them.
"""

from __future__ import annotations

import math

from build123d import Align, Axis, Box, Compound, Cylinder, Face, Line, Pos, Rot, Spline, Wire, extrude, fillet

from aicad.design import Design, Motion, Param, Part

TITLE = "Roman shade, top-down/bottom-up"
DESCRIPTION = "Cordless TDBU Roman shade: rails ride in side channels on hidden springs, or on hidden belts and motors."

PARAMS = {
    "window_width": Param(900, 400, 2400, description="Inside width of the window frame"),
    "window_height": Param(1200, 500, 2800, description="Inside height of the window frame"),
    "headrail_height": Param(45, 30, 100, description="Headrail height (houses the springs)"),
    "headrail_depth": Param(50, 35, 120, description="Headrail depth front to back"),
    "channel_width": Param(25, 16, 50, description="Side channel width across the window"),
    "channel_depth": Param(30, 20, 60, description="Side channel depth front to back"),
    "channel_wall": Param(2, 1, 4, description="Side channel wall thickness"),
    "mount_wall": Param(5, 3, 10, description="Wall against the frame (channels) and wall (headrail back); holds the joint pins"),
    "slot_width": Param(10, 4, 30, description="Opening in each channel that pins and carriers pass through"),
    "rail_height": Param(30, 15, 60, description="Middle and bottom rail height"),
    "rail_depth": Param(22, 12, 50, description="Middle and bottom rail depth"),
    "handle_length": Param(80, 0, 200, description="Pull handle length on each rail (0 = none)"),
    "fold_spacing": Param(180, 80, 400, description="Fabric length between battens"),
    "batten_size": Param(8, 4, 15, description="Batten thickness"),
    "fabric_thickness": Param(1.5, 0.5, 5, description="Fabric thickness"),
    "spring_diameter": Param(28, 12, 40, description="Constant-force spring coil diameter"),
    "tape_width": Param(8, 4, 20, description="Spring tape width"),
    "motorized": Param(0, 0, 1, unit="", description="Drive: 0 = springs (push by hand), 1 = motors and belts"),
    "motor_size": Param(20, 14, 28, description="Stepper body size (20 = NEMA 8, 28 = NEMA 11)"),
    "motor_length": Param(45, 25, 80, description="Motor length including its gearbox"),
    "pulley_diameter": Param(10, 6, 16, description="Belt pulley diameter (10 = GT2 16-tooth)"),
    "belt_width": Param(6, 4, 9, description="Timing belt width"),
    "print_pieces": Param(0, 0, 1, unit="", description="Show as printable pieces: 0 = assembled parts, 1 = pieces with pin joints"),
    "max_piece_length": Param(240, 100, 400, description="Longest printed piece (AnkerMake M5: 235 x 235 x 250)"),
    "pin_diameter": Param(1.75, 1.75, 4, description="Joint pin diameter (1.75 = a length of filament)"),
    "pin_clearance": Param(0.25, 0.1, 0.6, description="Extra hole size for the pins"),
    "screw_hole": Param(4, 3, 6, description="Mounting screw hole diameter"),
    "top_drop": Param(0, 0, 2000, description="Position: how far the top of the shade is lowered"),
    "bottom_raise": Param(0, 0, 2000, description="Position: how far the bottom of the shade is raised"),
}

C_MIN = (Align.CENTER, Align.CENTER, Align.MIN)


def build(
    window_width=900,
    window_height=1200,
    headrail_height=45,
    headrail_depth=50,
    channel_width=25,
    channel_depth=30,
    channel_wall=2,
    mount_wall=5,
    slot_width=10,
    rail_height=30,
    rail_depth=22,
    handle_length=80,
    fold_spacing=180,
    batten_size=8,
    fabric_thickness=1.5,
    spring_diameter=28,
    tape_width=8,
    motorized=0,
    motor_size=20,
    motor_length=45,
    pulley_diameter=10,
    belt_width=6,
    print_pieces=0,
    max_piece_length=240,
    pin_diameter=1.75,
    pin_clearance=0.25,
    screw_hole=4,
    top_drop=0,
    bottom_raise=0,
) -> Design:
    W, H = window_width, window_height
    cw, cd, wall = channel_width, channel_depth, channel_wall
    rh, rd, bt, ft = rail_height, rail_depth, batten_size, fabric_thickness
    top = H - headrail_height  # underside of the headrail
    mw = max(mount_wall, wall)
    inner_w = W - 2 * cw  # clear width between the channels
    inner_cw = cw - wall - mw  # inside width of a channel
    chan_x = W / 2 - mw - inner_cw / 2  # centre line of each channel's inside

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
        body = Pos(side * (W / 2 - cw / 2), 0, 0) * Box(cw, cd, top, align=C_MIN)
        body -= Pos(side * chan_x, 0, -1) * Box(inner_cw, cd - 2 * wall, top + 2, align=C_MIN)
        # Slot in the inboard wall for the rail tongues and batten pins.
        body -= Pos(side * (W / 2 - cw + wall / 2), 0, -1) * Box(wall * 2, slot_width, top + 2, align=C_MIN)
        return body

    channel_l, channel_r = channel(-1), channel(1)
    channels = channel_l + channel_r

    # ---------------- headrail with spring housings ----------------
    head = Pos(0, 0, top) * Box(W, headrail_depth, headrail_height, align=C_MIN)
    head = fillet(head.edges().filter_by(Axis.X).group_by(Axis.Y)[0], min(6, headrail_height / 4))
    head_back = headrail_depth / 2 - mw  # inside face of the (thicker) back wall
    head_front = -headrail_depth / 2 + wall
    head -= Pos(0, (head_back + head_front) / 2, top - 1) * Box(
        W - 2 * wall, head_back - head_front, headrail_height - wall + 1, align=C_MIN
    )

    motor_on = motorized >= 0.5
    inner_d = cd - 2 * wall
    springs, tapes = [], []
    drive, belts = [], []
    if not motor_on:
        # Each channel has two springs, one per rail. A coil's axis runs across the
        # window; its tape leaves the coil tangentially and drops straight down the
        # channel. The middle rail's tape runs down the front of the channel and the
        # bottom rail's down the back, and the two coils sit side by side so they
        # fit in the headrail.
        tape_y = {"middle": -(cd / 2 - wall - 3), "bottom": cd / 2 - wall - 3}
        tape_dx = {"middle": -min(tape_width / 2 + 1, inner_cw / 4), "bottom": min(tape_width / 2 + 1, inner_cw / 4)}
        coil_w = min(tape_width + 1, inner_cw / 2 - 0.5)
        # Each coil touches its tape's line on one side, so it reaches 2r towards the other wall.
        spring_r = min(
            spring_diameter / 2,
            headrail_height / 2 - wall - 0.5,
            (head_back - 0.5 - tape_y["middle"]) / 2,
            (tape_y["bottom"] - head_front - 0.5) / 2,
        )
        coil_z = top + headrail_height / 2
        for side in (-1, 1):
            for rail, carrier_top in (("middle", mid_top), ("bottom", bottom_raise + rh)):
                x = side * (chan_x + tape_dx[rail])  # inboard for the middle rail, outboard for the bottom
                y = tape_y[rail]
                coil_y = y + spring_r if rail == "middle" else y - spring_r
                springs.append(Pos(x, coil_y, coil_z) * Rot(0, 90, 0) * Cylinder(spring_r, coil_w))
                tapes.append(Pos(x, y, carrier_top) * Box(min(tape_width, coil_w), 0.4, coil_z - carrier_top, align=C_MIN))

    else:
        # Each channel splits in two: carriers ride in the inner half, belts run
        # in the outer half. Positions across the channel are `u`, measured
        # outwards from the channel centre line.
        half = inner_cw / 2
        bw = min(belt_width, half - 1)
        belt_u = half / 2 + 0.25
        pr = pulley_diameter / 2
        loop_y = {"middle": -(inner_d / 2 - pr - 1), "bottom": inner_d / 2 - pr - 1}
        pz = top + headrail_height / 2  # pulley and shaft height
        idler_z = pr + 3
        shaft_r = 2.5
        # The motors sit on their own shafts, so each must clear the other rail's shaft.
        msize = min(motor_size, headrail_height - 2 * wall - 1, 2 * (2 * abs(loop_y["middle"]) - shaft_r - 0.5))
        shaft_x = chan_x + belt_u
        for rail, motor_x in (("middle", -W / 4), ("bottom", W / 4)):
            yc = loop_y[rail]
            drive.append(Pos(0, yc, pz) * Rot(0, 90, 0) * Cylinder(shaft_r, 2 * shaft_x + bw + 2))
            body = Pos(motor_x, yc, pz) * Box(motor_length * 0.55, msize, msize)
            gear = Pos(motor_x + motor_length * 0.5, yc, pz) * Rot(0, 90, 0) * Cylinder(msize * 0.45, motor_length * 0.45)
            drive.extend([body, gear])
            for side in (-1, 1):
                x = side * shaft_x
                drive.append(Pos(x, yc, pz) * Rot(0, 90, 0) * Cylinder(pr, bw + 2))  # pulley
                drive.append(Pos(x, yc, idler_z) * Rot(0, 90, 0) * Cylinder(pr, bw + 2))  # idler
                for dy in (-pr, pr):  # the two strands of the loop
                    belts.append(Pos(x, yc + dy, idler_z) * Box(bw, 1.5, pz - idler_z, align=C_MIN))
        # Controller on the back wall of the headrail.
        drive.append(Pos(0, head_back - 3, top + wall + 2) * Box(60, 4, min(25, headrail_height - 2 * wall - 4), align=C_MIN))

    # ---------------- rails with end carriers ----------------
    def rail(z_bottom: float, carrier_y: float, carrier_d: float, clamp_y: float | None = None):
        body = Pos(0, 0, z_bottom) * Box(inner_w, rd, rh, align=C_MIN)
        body = fillet(body.edges().filter_by(Axis.X).group_by(Axis.Y)[0], min(4, rh / 4))
        for side in (-1, 1):
            # Tongue through the slot, then a carrier block inside the channel.
            body += Pos(side * (inner_w / 2 + wall), 0, z_bottom + rh / 2) * Box(wall * 2 + 2, slot_width - 1, rh * 0.6)
            if clamp_y is None:  # spring version: carrier fills the channel width, with friction pads
                body += Pos(side * chan_x, carrier_y, z_bottom) * Box(inner_cw - 1, carrier_d, rh, align=C_MIN)
            else:  # motor version: carrier in the inner half, plus an arm that clamps its belt strand
                cwid = inner_cw / 2 - 1
                body += Pos(side * (chan_x - inner_cw / 4 - 0.25), carrier_y, z_bottom) * Box(cwid, carrier_d, rh, align=C_MIN)
                arm_len = inner_cw / 2 + 0.5
                # The arm sits on the inner face of the strand, so it stays clear of the channel wall.
                arm_y = clamp_y + (1 if clamp_y < 0 else -1)
                body += Pos(side * (chan_x + arm_len / 2 - 1), arm_y, z_bottom + rh - 8) * Box(arm_len, 3, 8, align=C_MIN)
        if handle_length > 0:
            body += Pos(0, -rd / 2 - 4, z_bottom + rh / 2) * Box(handle_length, 8, rh * 0.35)
        return body

    if not motor_on:
        # Middle carrier stays in the front of the channel so the bottom rail's tape passes behind it.
        cd_in = inner_d - 1
        middle = rail(z0, -cd_in * 0.2, cd_in * 0.55)
        bottom = rail(bottom_raise, 0, cd_in)
    else:
        # Each carrier clamps the outer strand of its own loop: front for the middle rail, back for the bottom.
        middle = rail(z0, 0, inner_d - 1, clamp_y=loop_y["middle"] - pr)
        bottom = rail(bottom_raise, 0, inner_d - 1, clamp_y=loop_y["bottom"] + pr)

    # ---------------- battens with pins into the channels ----------------
    batten_y = ft + bt / 2  # just behind the fabric, inside its pocket
    battens = [
        Pos(0, batten_y, z) * Box(W - 2 * mw - 2, bt, bt) for z in anchors[1:-1]
    ]

    # ---------------- fabric: flat where taut, folded forward where slack ----------------
    folds = [_fabric_segment(a, b, pitch, ft, inner_w - 2) for a, b in zip(anchors[:-1], anchors[1:])]

    open_gap = (anchors[0] - anchors[-1]) > pitch * n_folds - 1
    PRINT = "Print in PETG"
    motions = [
        Motion.from_param("lower_top", "top_drop", (0, top - 2 * rh - stack)),
        Motion.from_param("raise_bottom", "bottom_raise", (0, top - 2 * rh - stack)),
    ]
    notes = (
        f"{n_folds} folds of {pitch:.0f} mm, {n_battens} battens. "
        + ("Shade fully closed. " if open_gap and top_drop == 0 and bottom_raise == 0 else "")
        + (
            "No lift cords: rails are carried by constant-force springs inside the channels and held by friction pads."
            if not motor_on
            else "Motorized: each rail is driven at both ends by belts inside the channels; the geared motors hold it with the power off."
        )
    )
    bought = [
        *([Part("springs", Compound(springs + tapes), color="#8f99a6", explode=(0, 0, headrail_height * 3),
                material="Buy: 4 constant-force springs (steel tape)")] if not motor_on else [
           Part("drive", Compound(drive), color="#5b6470", explode=(0, 0, headrail_height * 3),
                material="Buy: 2 geared steppers, 2 shafts, 4 GT2 pulleys + 4 idlers, ESP32 + 2 TMC2209"),
           Part("belts", Compound(belts), color="#c9772b", explode=(0, 0, 0), material="Buy: GT2 timing belt"),
        ]),
        Part("fabric", Compound(folds), color="#e8dcc4", explode=(0, -rd * 3, 0), material="Buy: fabric"),
        Part("battens", Compound(battens) if battens else Box(1, 1, 1), color="#a0724a", explode=(0, rd * 4, 0),
             material=f"Buy: {n_battens} x {bt:g} mm dowels, {W - 2 * mw - 2:.0f} mm long"),
    ]

    if print_pieces < 0.5:
        return Design(
            name="roman_shade",
            parts=[
                Part("headrail", head, color="#d7dbe0", explode=(0, 0, headrail_height * 3), material="Aluminium or printed PETG"),
                bought[0] if not motor_on else bought[0],
                *(bought[1:2] if motor_on else []),
                Part("channels", channels, color="#c3c9d1", explode=(0, 0, 0), material="Aluminium or printed PETG"),
                Part("middle_rail", middle, color="#4f7cac", explode=(0, -rd * 6, 0), material="Aluminium + printed carriers"),
                Part("bottom_rail", bottom, color="#3d5f86", explode=(0, -rd * 6, 0), material="Aluminium + printed carriers"),
                *bought[-2:],
            ],
            motions=motions,
            notes=notes,
        )

    # ---------------- printable pieces ----------------
    pin_r = (pin_diameter + pin_clearance) / 2
    pin_depth = 10
    sx = (-1, 1)
    printed: list[Part] = []
    pin_parts: list[Part] = []
    pin_count = 0

    def pieces(name, shape, axis, pin_spots, screws, color, explode):
        """Cut `shape` into pieces along `axis` (0=X, 2=Z) with pin holes at each cut."""
        nonlocal pin_count
        pins = []
        bb = shape.bounding_box()
        lo, hi = (bb.min.X, bb.max.X) if axis == 0 else (bb.min.Z, bb.max.Z)
        n = max(1, math.ceil((hi - lo) / max_piece_length))
        cuts = [lo + (hi - lo) * k / n for k in range(1, n)]
        for ci, c in enumerate(cuts, start=1):
            cut_pins = []
            for a, b in pin_spots:
                if axis == 0:
                    hole = Pos(c, a, b) * Rot(0, 90, 0) * Cylinder(pin_r, 2 * pin_depth)
                    pin = Pos(c, a, b) * Rot(0, 90, 0) * Cylinder(pin_diameter / 2, 2 * pin_depth - 1)
                else:
                    hole = Pos(a, b, c) * Cylinder(pin_r, 2 * pin_depth)
                    pin = Pos(a, b, c) * Cylinder(pin_diameter / 2, 2 * pin_depth - 1)
                shape = shape - hole
                cut_pins.append(pin)
            pins.append((ci, cut_pins))
        edges = [lo - 1] + cuts + [hi + 1]
        big = 10 * max(W, H)
        gap = 30
        for k in range(n):
            a, b = edges[k], edges[k + 1]
            if axis == 0:
                slab = Pos((a + b) / 2, 0, H / 2) * Box(b - a, big, big)
            else:
                slab = Pos(0, 0, (a + b) / 2) * Box(big, big, b - a)
            piece = shape & slab
            for spot in screws(a, b):
                piece = piece - spot
            offset = (k - (n - 1) / 2) * gap
            ex = (explode[0] + (offset if axis == 0 else 0), explode[1], explode[2] + (offset if axis == 2 else 0))
            printed.append(Part(f"{name}_{k + 1}", piece, color=color, explode=ex, material=PRINT))
        for ci, cut_pins in pins:
            # When exploded, each joint's pins sit halfway between the two pieces they join.
            offset = (ci - n / 2) * gap
            ex = (explode[0] + (offset if axis == 0 else 0), explode[1], explode[2] + (offset if axis == 2 else 0))
            pin_count += len(cut_pins)
            pin_parts.append(Part(f"pins_{name}_{ci}", Compound(cut_pins), color="#e04f4f", explode=ex,
                                  material=f"{len(cut_pins)} pins: {pin_diameter:g} mm filament cut to {2 * pin_depth - 1} mm"))

    # Headrail: pins in the thick back wall; screw holes up through the top into the head of the frame.
    hz = headrail_height
    pieces(
        "headrail", head, 0,
        [((head_back + headrail_depth / 2) / 2, top + hz * f) for f in (0.3, 0.7)],
        lambda a, b: [Pos(a + (b - a) * f, 0, top + hz - wall / 2) * Cylinder(screw_hole / 2, wall * 3) for f in (0.25, 0.75)],
        "#d7dbe0", (0, 0, hz * 3),
    )
    # Channels: pins in the thick frame-side wall; screw holes through it into the frame.
    for side, chan, label in ((-1, channel_l, "channel_left"), (1, channel_r, "channel_right")):
        wall_x = side * (W / 2 - mw / 2)
        pieces(
            label, chan, 2,
            [(wall_x, y) for y in (-cd / 4, cd / 4)],
            lambda a, b, wall_x=wall_x: [
                Pos(wall_x, 0, a + (b - a) * f) * Rot(0, 90, 0) * Cylinder(screw_hole / 2, mw * 3) for f in (0.25, 0.75)
            ],
            "#c3c9d1", (side * 60, 0, 0),
        )
    # Rails: two pins through the solid section at each cut.
    for name, shape, zb, color in (("middle_rail", middle, z0, "#4f7cac"), ("bottom_rail", bottom, bottom_raise, "#3d5f86")):
        pieces(name, shape, 0, [(0, zb + rh * f) for f in (0.3, 0.7)], lambda a, b: [], color, (0, -rd * 6, 0))

    longest = max(max(tuple(p.shape.bounding_box().size)) for p in printed)
    return Design(
        name="roman_shade",
        parts=[
            *printed,
            *pin_parts,
            *bought,
        ],
        motions=motions,
        notes=(
            f"{len(printed)} printed pieces, longest {longest:.0f} mm (print standing up), "
            f"joined with {pin_count} filament pins. " + notes
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
