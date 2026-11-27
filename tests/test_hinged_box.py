import pytest
from build123d import Axis

from aicad import registry


@pytest.fixture(scope="module")
def box():
    design, _ = registry.build("hinged_box")
    return design


def test_parts_are_valid_solids(box):
    assert [p.name for p in box.parts] == ["base", "lid", "pin"]
    for p in box.parts:
        assert p.shape.is_valid
        assert p.shape.volume > 0


def test_closed_assembly_has_no_interference(box):
    base, lid, pin = (box.part(n).shape for n in ("base", "lid", "pin"))
    assert (base & lid).volume == pytest.approx(0, abs=1e-6)
    assert (base & pin).volume == pytest.approx(0, abs=1e-6)
    assert (lid & pin).volume == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize("angle", [20, 45, 90, 110])
def test_lid_swings_clear_of_base(box, angle):
    motion = box.motions[0]
    lid = box.part("lid").shape.rotate(Axis(motion.origin, motion.direction), angle)
    assert (box.part("base").shape & lid).volume == pytest.approx(0, abs=1e-6)


def test_viewer_motion_matches_build123d_joint():
    """Rotating by the exported Motion must equal moving the lid with the CAD joint."""
    design, _ = registry.build("hinged_box", {"width": 90})  # fresh build, not the cached one
    motion = design.motions[0]
    closed_lid = design.part("lid").shape
    expected = closed_lid.rotate(Axis(motion.origin, motion.direction), 60).bounding_box()

    base = design.part("base").shape
    base.joints["hinge"].connect_to(closed_lid.joints["hinge"], angle=60)
    actual = closed_lid.bounding_box()
    for a, b in ((actual.min, expected.min), (actual.max, expected.max)):
        assert (a - b).length == pytest.approx(0, abs=1e-6)


def test_params_change_geometry_and_are_clamped():
    design, resolved = registry.build("hinged_box", {"width": 120, "height": 9999})
    bb = design.part("base").shape.bounding_box()
    assert bb.size.X == pytest.approx(120)
    assert resolved["height"] == 200  # clamped to Param.max


def test_unknown_param_is_rejected():
    with pytest.raises(ValueError):
        registry.build("hinged_box", {"colour": 1})
