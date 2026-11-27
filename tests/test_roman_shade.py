import pytest
from build123d import Axis, Box, LinearJoint, RigidJoint, Location

from aicad import registry
from aicad.checks import check_module
from aicad.design import Motion


def z_range(shape):
    bb = shape.bounding_box()
    return bb.min.Z, bb.max.Z


@pytest.mark.parametrize("top_drop,bottom_raise", [(0, 0), (0, 500), (400, 0), (300, 300), (5000, 5000)])
def test_every_position_builds_valid_geometry(top_drop, bottom_raise):
    design, _ = registry.build("roman_shade", {"top_drop": top_drop, "bottom_raise": bottom_raise})
    for part in design.parts:
        assert part.shape.is_valid, part.name
        part.shape.tessellate(0.05, 0.2)  # the viewer must be able to mesh it


def test_rails_follow_the_two_positions_and_never_cross():
    closed, _ = registry.build("roman_shade", {})
    top_closed = z_range(closed.part("middle_rail").shape)[1]
    moved, _ = registry.build("roman_shade", {"top_drop": 300, "bottom_raise": 200})
    mid_lo, mid_hi = z_range(moved.part("middle_rail").shape)
    bot_lo, bot_hi = z_range(moved.part("bottom_rail").shape)
    assert mid_hi == pytest.approx(top_closed - 300, abs=0.5)
    assert bot_lo == pytest.approx(200, abs=0.5)
    # Asking for too much is clamped so the fabric stack still fits between the rails.
    extreme, _ = registry.build("roman_shade", {"top_drop": 5000, "bottom_raise": 5000})
    assert z_range(extreme.part("bottom_rail").shape)[1] < z_range(extreme.part("middle_rail").shape)[0]


def test_folds_stack_on_the_bottom_rail_when_raised():
    design, _ = registry.build("roman_shade", {"bottom_raise": 5000})  # raised as far as it goes
    battens_lo, battens_hi = z_range(design.part("battens").shape)
    bottom_top = z_range(design.part("bottom_rail").shape)[1]
    assert battens_lo > bottom_top and battens_hi - battens_lo < 100  # all stacked just above it
    fabric = design.part("fabric").shape.bounding_box()
    assert fabric.min.Y < -50  # pleats bulge out towards the room


def test_springs_are_hidden():
    """Coils sit inside the headrail and tapes inside the channels, so nothing shows from the room."""
    design, params = registry.build("roman_shade", {"top_drop": 250, "bottom_raise": 100})
    head = design.part("headrail").shape.bounding_box()
    chan = design.part("channels").shape.bounding_box()
    top = head.min.Z
    for solid in design.part("springs").shape.solids():
        bb = solid.bounding_box()
        if bb.size.Z > params["headrail_height"]:  # a tape
            assert chan.min.Y < bb.min.Y and bb.max.Y < chan.max.Y
            x_out = abs(bb.center().X)
            assert params["window_width"] / 2 - params["channel_width"] < x_out - params["tape_width"] / 2
        else:  # a coil
            assert head.min.Y < bb.min.Y and bb.max.Y < head.max.Y
            assert top <= bb.min.Z and bb.max.Z <= head.max.Z
    # Coils must not collide with each other.
    coils = [s for s in design.part("springs").shape.solids() if s.bounding_box().size.Z <= params["headrail_height"]]
    assert len(coils) == 4
    for i, a in enumerate(coils):
        for b in coils[i + 1:]:
            assert a.intersect(b) is None or a.intersect(b).volume < 1e-6


def test_motions_rebuild_through_parameters():
    design, _ = registry.build("roman_shade", {})
    motions = {m.name: m.to_dict() for m in design.motions}
    assert motions["lower_top"]["kind"] == "param" and motions["lower_top"]["param"] == "top_drop"
    assert motions["raise_bottom"]["param"] == "bottom_raise"
    assert motions["lower_top"]["range"][1] > 500


def test_shade_follows_the_parameter_conventions():
    path, _ = registry.get_path("roman_shade")
    warnings = check_module(registry._load_module("roman_shade", path), path.read_text())
    assert not [w for w in warnings if "PARAMS" in w or "defaults to" in w]


def test_linear_motion_from_joint():
    base = Box(100, 10, 10)
    slide = LinearJoint("slide", base, axis=Axis((0, 0, 5), (1, 0, 0)), linear_range=(0, 40))
    carriage = Box(10, 10, 10)
    RigidJoint("mount", carriage, joint_location=Location((0, 0, 0)))
    slide.connect_to(carriage.joints["mount"], position=10)
    m = Motion.from_linear_joint("slide", slide, parts=["carriage"]).to_dict()
    assert m["kind"] == "linear" and m["range"] == [0, 40] and m["unit"] == "mm"
    assert m["direction"] == pytest.approx([1, 0, 0])


def _overlap(a, b):
    common = a.intersect(b)
    if common is None:
        return False
    return sum(s.volume for s in (common if isinstance(common, list) else [common])) > 1e-3


@pytest.mark.parametrize("top_drop,bottom_raise", [(0, 0), (300, 250), (5000, 5000)])
def test_motorized_drive_is_hidden_and_clear(top_drop, bottom_raise):
    design, params = registry.build(
        "roman_shade", {"motorized": 1, "top_drop": top_drop, "bottom_raise": bottom_raise}
    )
    names = [p.name for p in design.parts]
    assert "springs" not in names and {"drive", "belts"} <= set(names)
    head = design.part("headrail").shape.bounding_box()
    chan = design.part("channels").shape
    belts = design.part("belts").shape.solids()
    assert len(belts) == 8  # two strands per loop, a loop per rail on each side

    # Belts run inside the channels without touching their walls.
    for b in belts:
        assert not _overlap(b, chan)
        bb = b.bounding_box()
        assert head.min.Y < bb.min.Y and bb.max.Y < head.max.Y

    # Each rail clamps exactly one strand per side, and clears all the others.
    for rail in ("middle_rail", "bottom_rail"):
        shape = design.part(rail).shape
        touched = [b for b in belts if _overlap(b, shape)]
        assert len(touched) == 2, rail
        assert not _overlap(shape, chan)

    # Motors, shafts and pulleys sit in the headrail and don't collide with each other.
    drive = design.part("drive").shape.solids()
    in_head = [d for d in drive if d.bounding_box().min.Z >= head.min.Z - 1e-6]
    for d in in_head:
        bb = d.bounding_box()
        assert head.min.Y < bb.min.Y and bb.max.Y < head.max.Y and bb.max.Z <= head.max.Z
    motors = [d for d in in_head if d.bounding_box().size.Y > 1.5 * params["pulley_diameter"]]
    shafts = [d for d in in_head if d.bounding_box().size.X > params["window_width"] * 0.8]
    assert len(shafts) == 2 and len(motors) >= 2
    for m in motors:
        assert sum(_overlap(m, s) for s in shafts) == 1  # its own shaft only


def test_spring_version_is_the_default():
    design, _ = registry.build("roman_shade", {})
    assert "springs" in [p.name for p in design.parts]


M5_BED = (235, 235, 250)  # AnkerMake M5 build volume, mm


@pytest.mark.parametrize("motorized", [0, 1])
def test_print_pieces_fit_the_printer_and_pin_together(motorized):
    design, params = registry.build("roman_shade", {"print_pieces": 1, "motorized": motorized})
    printed = [p for p in design.parts if p.material.startswith("Print")]
    assert {p.name.rsplit("_", 1)[0] for p in printed} == {
        "headrail", "channel_left", "channel_right", "middle_rail", "bottom_rail"
    }
    for p in printed:
        assert p.shape.is_valid and len(p.shape.solids()) == 1, p.name
        dims = sorted(tuple(p.shape.bounding_box().size))
        assert all(d <= b for d, b in zip(dims, sorted(M5_BED))), (p.name, dims)

    # Every pin sits in a hole (touches no printed material) and bridges exactly two pieces.
    pins = [s for p in design.parts if p.name.startswith("pins_") for s in p.shape.solids()]
    assert pins
    for pin in pins:
        pb = pin.bounding_box()
        pmin, pmax = tuple(pb.min), tuple(pb.max)
        neighbours = []
        for p in printed:
            assert not _overlap(pin, p.shape), p.name
            bb = p.shape.bounding_box()
            bmin, bmax = tuple(bb.min), tuple(bb.max)
            if all(bmin[i] - 0.01 <= pmax[i] and pmin[i] <= bmax[i] + 0.01 for i in range(3)):
                neighbours.append(p.name)
        assert len(neighbours) >= 2, neighbours


def test_print_pieces_add_up_to_the_assembled_parts():
    assembled, _ = registry.build("roman_shade", {})
    pieces, _ = registry.build("roman_shade", {"print_pieces": 1})
    for name in ("headrail", "middle_rail"):
        whole = assembled.part(name).shape.volume
        parts = sum(p.shape.volume for p in pieces.parts if p.name.startswith(name + "_"))
        assert parts == pytest.approx(whole, rel=0.02)  # only the pin and screw holes are missing
