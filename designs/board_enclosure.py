"""Enclosure for a small dev board: a base with screw bosses and a USB-C opening, and a vented lid."""
from build123d import *
from aicad.design import Design, Param, Part

TITLE = "Dev board enclosure"
DESCRIPTION = "Two-part printable box for an ESP32-size board: screw-down lid, USB-C opening, vent slots."

PARAMS = {
    "board_length": Param(55, 20, 150, description="Board length (X)"),
    "board_width": Param(28, 15, 100, description="Board width (Y)"),
    "board_clearance": Param(1.5, 0.5, 5, description="Gap around the board"),
    "inner_height": Param(20, 8, 80, description="Inside height, floor to lid"),
    "wall": Param(2, 1.2, 5, description="Wall thickness"),
    "floor": Param(2, 1.2, 5, description="Floor thickness"),
    "lid_thickness": Param(2, 1.2, 5, description="Lid thickness"),
    "screw_diameter": Param(2.5, 2, 4, description="Lid screw size (2.5 = M2.5)"),
    "usb_width": Param(10, 6, 20, description="USB opening width"),
    "usb_height": Param(5, 3, 12, description="USB opening height"),
    "usb_z": Param(4, 0, 30, description="USB opening centre height above the floor"),
    "vent_count": Param(6, 0, 20, unit="", description="Number of vent slots in the lid"),
    "vent_width": Param(2, 1, 5, description="Vent slot width"),
    "tab_length": Param(10, 0, 30, description="Wall-mount tab length past each end (0 = no tabs)"),
    "tab_hole": Param(4, 2, 8, description="Wall-mount screw hole diameter"),
}


def build(board_length=55, board_width=28, board_clearance=1.5, inner_height=20, wall=2, floor=2,
          lid_thickness=2, screw_diameter=2.5, usb_width=10, usb_height=5, usb_z=4,
          vent_count=6, vent_width=2, tab_length=10, tab_hole=4) -> Design:
    boss_d = screw_diameter + 4
    inner_x = board_length + 2 * board_clearance + 2 * boss_d
    inner_y = board_width + 2 * board_clearance
    outer_x, outer_y = inner_x + 2 * wall, inner_y + 2 * wall
    H = floor + inner_height
    r = min(3, outer_y / 6)
    boss_x = inner_x / 2 - boss_d / 2
    boss_y = inner_y / 2 - boss_d / 2
    boss_pts = [(sx * boss_x, sy * boss_y) for sx in (-1, 1) for sy in (-1, 1)]

    # Base: rounded shell, four screw bosses in the corners, USB slot in the +X end wall.
    outer = fillet(Box(outer_x, outer_y, H, align=(Align.CENTER, Align.CENTER, Align.MIN)).edges().filter_by(Axis.Z), r)
    pocket = Pos(0, 0, floor) * Box(inner_x, inner_y, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
    base = outer - pocket
    for x, y in boss_pts:
        base += Pos(x, y, floor) * Cylinder(boss_d / 2, inner_height, align=(Align.CENTER, Align.CENTER, Align.MIN))
        base -= Pos(x, y, floor + 1) * Cylinder(screw_diameter * 0.4, inner_height, align=(Align.CENTER, Align.CENTER, Align.MIN))
    usb = Pos(outer_x / 2, 0, floor + usb_z) * fillet(Box(wall * 3, usb_width, usb_height).edges().filter_by(Axis.X), min(1.5, usb_height / 2 - 0.1))
    base -= usb

    # Wall-mount tabs off both short ends, flush with the floor, each with a screw hole.
    if tab_length > 0:
        tab_t = max(floor, 3)
        tab_y = min(outer_y * 0.6, tab_hole * 3)
        for sx in (-1, 1):
            cx = sx * (outer_x / 2 + (tab_length - r) / 2)
            tab = Pos(cx, 0, 0) * Box(tab_length + r, tab_y, tab_t, align=(Align.CENTER, Align.CENTER, Align.MIN))
            tab = fillet(tab.edges().filter_by(Axis.Z).group_by(Axis.X)[0 if sx < 0 else -1], tab_y / 2 - 0.01)
            base += tab
            base -= Pos(sx * (outer_x / 2 + tab_length - tab_y / 2), 0, 0) * Cylinder(tab_hole / 2, tab_t, align=(Align.CENTER, Align.CENTER, Align.MIN))

    # Lid: plate with clearance holes over the bosses and a row of vent slots.
    lid = Pos(0, 0, H) * fillet(Box(outer_x, outer_y, lid_thickness, align=(Align.CENTER, Align.CENTER, Align.MIN)).edges().filter_by(Axis.Z), r)
    for x, y in boss_pts:
        lid -= Pos(x, y, H) * Cylinder(screw_diameter / 2 + 0.2, lid_thickness, align=(Align.CENTER, Align.CENTER, Align.MIN))
    n = int(vent_count)
    if n:
        pitch = min(vent_width * 2.2, (inner_x - 2 * boss_d - 4) / n)
        slot_len = inner_y * 0.6
        for i in range(n):
            x = (i - (n - 1) / 2) * pitch
            lid -= \
                Pos(x, 0, H) * extrude(SlotCenterToCenter(slot_len - vent_width, vent_width, rotation=90), lid_thickness)

    return Design(
        name="board_enclosure",
        parts=[
            Part("base", base, color="#4f7cac", material="PETG"),
            Part("lid", lid, color="#e0a458", explode=(0, 0, inner_height * 0.8), material="PETG"),
        ],
        notes=f"Fits a {board_length:g} x {board_width:g} mm board. Lid screws: 4x M{screw_diameter:g} x 8 self-tapping.",
    )
