"""Hinged box: a printable box, a lid and a hinge pin, joined with build123d joints.

The base carries a RevoluteJoint along the back edge. The lid is modelled in
its own local frame and placed by connecting its RigidJoint to that hinge, so
the viewer's lid animation comes straight from the CAD joint.
"""

from build123d import (
    Align,
    Axis,
    Box,
    Cylinder,
    Location,
    Pos,
    RevoluteJoint,
    RigidJoint,
    Rot,
    fillet,
)

from aicad.design import Design, Motion, Param, Part

TITLE = "Hinged box"
DESCRIPTION = "Three-part printable box with a pinned knuckle hinge along the back edge."

PARAMS = {
    "width": Param(80, 40, 250, description="Outer width (X)"),
    "depth": Param(60, 30, 250, description="Outer depth (Y)"),
    "height": Param(40, 15, 200, description="Base height (Z), not counting the lid"),
    "wall": Param(2.4, 1.2, 6, description="Wall and floor thickness"),
    "lid_thickness": Param(3, 2, 8, description="Lid plate thickness"),
    "pin_diameter": Param(3, 1.75, 6, description="Hinge pin diameter (1.75 = filament as a pin)"),
    "clearance": Param(0.3, 0.1, 0.8, description="Gap between moving surfaces for printing"),
    "max_open": Param(110, 60, 180, unit="deg", description="How far the lid may open"),
}

CC_MIN = (Align.CENTER, Align.CENTER, Align.MIN)


def build(
    width=80,
    depth=60,
    height=40,
    wall=2.4,
    lid_thickness=3,
    pin_diameter=3,
    clearance=0.3,
    max_open=110,
) -> Design:
    W, D, H, w, T, c = width, depth, height, wall, lid_thickness, clearance

    # Hinge geometry: knuckles of radius R on an axis just behind the back
    # wall, at the lid's mid-thickness so the lid swings clear of the base.
    R = max(T / 2 + 2.5, pin_diameter / 2 + 1.6)
    axis_y = D / 2 + R
    axis_z = H + T / 2
    span = W * 0.6  # total length of the knuckle row
    seg = (span - 2 * c) / 3  # base | lid | base
    hole_r = pin_diameter / 2 + c / 2

    def knuckle(x0: float, x1: float, below_to: float):
        """A knuckle cylinder on the hinge axis plus a web joining it to its part."""
        length = x1 - x0
        cyl = Pos((x0 + x1) / 2, axis_y, axis_z) * Rot(0, 90, 0) * Cylinder(R, length)
        web_h = axis_z - below_to
        web = Pos((x0 + x1) / 2, (D / 2 + axis_y) / 2, below_to + web_h / 2) * Box(length, R, web_h)
        return cyl + web

    def pin_hole():
        return Pos(0, axis_y, axis_z) * Rot(0, 90, 0) * Cylinder(hole_r, span + 2)

    # ---------------- Base ----------------
    outer = Box(W, D, H, align=CC_MIN)
    outer = fillet(outer.edges().filter_by(Axis.Z), radius=min(4, W / 10, D / 10))
    pocket = Pos(0, 0, w) * Box(W - 2 * w, D - 2 * w, H, align=CC_MIN)
    base = outer - pocket
    base += knuckle(-span / 2, -span / 2 + seg, below_to=axis_z - R - 2)
    base += knuckle(span / 2 - seg, span / 2, below_to=axis_z - R - 2)
    base -= pin_hole()
    base.label = "base"

    hinge = RevoluteJoint(
        "hinge",
        base,
        axis=Axis((0, axis_y, axis_z), (-1, 0, 0)),
        angular_range=(0, max_open),
    )
    RigidJoint("pin_seat", base, joint_location=Location((0, axis_y, axis_z)))

    # ---------------- Lid (built in its own frame: plate bottom at z=0) ----------------
    lid = Pos(0, -c / 2, 0) * Box(W, D - c, T, align=CC_MIN)
    lid = fillet(lid.edges().filter_by(Axis.Z), radius=min(4, W / 10, D / 10))
    # Locating lip that drops just inside the base opening.
    lip_h = min(3, H / 4)
    lip_w = 1.2
    lip_outer = Box(W - 2 * w - 2 * c, D - 2 * w - 2 * c, lip_h, align=(Align.CENTER, Align.CENTER, Align.MAX))
    lip_inner = Box(W - 2 * w - 2 * c - 2 * lip_w, D - 2 * w - 2 * c - 2 * lip_w, lip_h, align=(Align.CENTER, Align.CENTER, Align.MAX))
    lid += lip_outer - lip_inner
    # Lid knuckle, expressed in world coords then shifted into the lid frame (z - H).
    lid_knuckle = knuckle(-seg / 2, seg / 2, below_to=H)
    lid_knuckle -= pin_hole()
    lid += Pos(0, 0, -H) * lid_knuckle
    lid.label = "lid"

    # Lid's attachment point: the hinge axis in the lid's own frame, oriented
    # like the base's revolute joint so angle 0 means "closed".
    RigidJoint(
        "hinge",
        lid,
        joint_location=Location((0, axis_y, T / 2), hinge.relative_axis.location.orientation),
    )
    hinge.connect_to(lid.joints["hinge"], angle=0)

    # ---------------- Pin ----------------
    pin = Rot(0, 90, 0) * Cylinder(pin_diameter / 2, span, align=CC_MIN)
    pin = Pos(-span / 2, 0, 0) * pin
    pin.label = "pin"
    RigidJoint("seat", pin, joint_location=Location((0, 0, 0)))
    base.joints["pin_seat"].connect_to(pin.joints["seat"])

    return Design(
        name="hinged_box",
        parts=[
            Part("base", base, color="#4f7cac", explode=(0, 0, 0), material="PLA"),
            Part("lid", lid, color="#e0a458", explode=(0, 0, H * 0.9), material="PLA"),
            Part("pin", pin, color="#c0c5cc", explode=(-(W * 0.5 + span * 0.6), 0, 0), material="1.75 mm filament or 3 mm steel rod"),
        ],
        motions=[Motion.from_revolute_joint("lid_open", hinge, parts=["lid"])],
        notes=(
            "Print base and lid as modelled (lid flat, lip down needs supports; "
            "flip lid lip-up to print support-free). Pin can be a length of filament."
        ),
    )
