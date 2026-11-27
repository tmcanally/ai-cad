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
