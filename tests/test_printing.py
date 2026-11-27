"""Print preparation: which parts print, orientation, supports, arrangement, 3MF and slicing."""

import re
import zipfile
from itertools import combinations

import pytest
from build123d import Box, Cylinder, Pos, Rot

from aicad import printing, registry
from aicad.design import Design, Part

M5 = printing.PRINTERS["ankermake_m5"]
needs_slicer = pytest.mark.skipif(printing.find_slicer() is None, reason="PrusaSlicer not installed")


def footprint_box(p):
    """Axis-aligned footprint of a planned piece on the bed (min x, min y, max x, max y), brim included."""
    cx, cy = p.position
    if p.orientation.diagonal:
        w = d = p.orientation.size[0] + 2 * p.brim
    else:
        w, d = printing._fp(p)
    return cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2


def assert_on_bed_without_overlap(plan):
    for plate in plan.plates:
        boxes = []
        for p in plate.pieces:
            x0, y0, x1, y1 = footprint_box(p)
            assert x0 >= -0.01 and y0 >= -0.01 and x1 <= M5.bed[0] + 0.01 and y1 <= M5.bed[1] + 0.01, p.name
            boxes.append((p, (x0, y0, x1, y1)))
        if plate.diagonal:
            continue  # diagonal strips overlap as boxes but not as strips
        for (a, ba), (b, bb) in combinations(boxes, 2):
            overlap = ba[0] < bb[2] - 0.01 and bb[0] < ba[2] - 0.01 and ba[1] < bb[3] - 0.01 and bb[1] < ba[3] - 0.01
            assert not overlap, (a.name, b.name)


def test_printable_guess_from_material():
    assert printing.is_printable(Part("a", Box(1, 1, 1), material="PLA"))[0]
    assert printing.is_printable(Part("a", Box(1, 1, 1)))[0]
    assert printing.is_printable(Part("a", Box(1, 1, 1), material="Print in PETG"))[0]
    assert not printing.is_printable(Part("a", Box(1, 1, 1), material="Buy: fabric"))[0]
    assert not printing.is_printable(Part("a", Box(1, 1, 1), material="6 mm birch ply"))[0]
    assert not printing.is_printable(Part("a", Box(1, 1, 1), material="2 pins: 1.75 mm filament cut to 19 mm"))[0]
    assert not printing.is_printable(Part("a", Box(1, 1, 1), material="Buy", printable=None))[0]
    assert printing.is_printable(Part("a", Box(1, 1, 1), material="Buy", printable=True))[0]
    assert printing.filament_for(Part("a", Box(1, 1, 1), material="Print in PETG")) == "PETG"


def test_flat_box_prints_on_its_bottom_without_supports():
    plan = printing.plan_print(Design("t", [Part("plate", Box(80, 60, 5))]))
    (p,) = plan.pieces
    assert p.orientation.side in ("bottom", "top") and not p.supports and p.brim == 0


def test_t_shape_turns_over_to_avoid_supports():
    # A wide cap on a narrow stem: upside down (cap on the bed) has no overhangs.
    tee = Pos(0, 0, 25) * Box(60, 60, 10) + Pos(0, 0, 10) * Box(15, 15, 20)
    plan = printing.plan_print(Design("t", [Part("tee", tee)]))
    assert plan.pieces[0].orientation.side == "top" and not plan.pieces[0].supports
    # Forced the other way up, it needs supports.
    forced = printing.plan_print(Design("t", [Part("tee", tee)]), part_settings={"tee": {"orientation": "bottom"}})
    assert forced.pieces[0].supports


def test_small_horizontal_holes_need_no_supports():
    bar = Box(100, 20, 20) - Pos(0, 0, 0) * Rot(0, 90, 0) * Cylinder(1.5, 120)
    plan = printing.plan_print(Design("t", [Part("bar", bar)]))
    assert not plan.pieces[0].supports


def test_long_part_goes_across_the_diagonal_and_huge_part_is_reported():
    plan = printing.plan_print(Design("t", [Part("long", Box(280, 20, 10)), Part("huge", Box(400, 300, 300))]))
    assert [p.part for p in plan.pieces] == ["long"]
    assert plan.pieces[0].orientation.diagonal
    assert plan.too_big[0]["part"] == "huge"
    assert_on_bed_without_overlap(plan)


def test_settings_overrides_and_validation():
    d = Design("t", [Part("a", Box(20, 20, 20), print_settings={"infill": 40}), Part("b", Box(20, 20, 20))])
    plan = printing.plan_print(d, {"walls": 4, "filament": "PETG"}, {"b": {"infill": 60, "copies": 3}})
    by = {p.name: p for p in plan.pieces}
    assert by["a"].settings.infill == 40 and by["a"].settings.walls == 4
    assert by["b"].settings.infill == 60 and {"b#2", "b#3"} <= set(by)
    assert {p.filament for p in plan.pieces} == {"PETG"}
    with pytest.raises(ValueError):
        printing.plan_print(d, {"infil": 10})
    with pytest.raises(ValueError):
        printing.plan_print(d, part_settings={"nope": {}})
    with pytest.raises(ValueError):
        printing.plan_print(d, part_settings={"a": {"orientation": "sideways"}})


def test_many_parts_fill_several_plates_inside_the_bed():
    d = Design("t", [Part(f"p{i}", Box(70, 50, 10)) for i in range(20)])
    plan = printing.plan_print(d)
    assert len(plan.pieces) == 20 and len(plan.plates) >= 2
    assert_on_bed_without_overlap(plan)


def test_roman_shade_pieces_plan():
    design, _ = registry.build("roman_shade", {"print_pieces": 1})
    plan = printing.plan_print(design)
    assert len(plan.pieces) == 22 and not plan.too_big
    skipped = {s["part"] for s in plan.skipped}
    assert {"fabric", "springs", "battens"} <= skipped and any(s.startswith("pins_") for s in skipped)
    assert not any(p.supports for p in plan.pieces)
    assert {p.filament for p in plan.pieces} == {"PETG"}
    assert_on_bed_without_overlap(plan)


def test_3mf_has_placed_objects_and_per_object_settings(tmp_path):
    d = Design("t", [Part("a", Box(30, 20, 10)), Part("b", Box(20, 20, 40), print_settings={"infill": 55})])
    plan = printing.plan_print(d)
    out = printing.write_print_job(plan, d, tmp_path, slice=False)
    path = out["plates"][0]["project_3mf"]
    with zipfile.ZipFile(path) as zf:
        model = zf.read("3D/3dmodel.model").decode()
        objcfg = zf.read("Metadata/Slic3r_PE_model.config").decode()
        cfg = zf.read("Metadata/Slic3r_PE.config").decode()
    assert model.count("<item ") == 2
    assert 'key="fill_density" value="55%"' in objcfg
    assert "; bed_shape = 0x0,235x0,235x235,0x235" in cfg
    assert (tmp_path / "PRINT-LIST.md").exists() and (tmp_path / "plan.json").exists()


@needs_slicer
def test_slices_to_gcode_inside_the_bed(tmp_path):
    d = Design("t", [Part("a", Box(40, 30, 6), material="PETG"), Part("b", Box(20, 20, 30), material="PETG")])
    out = printing.write_print_job(printing.plan_print(d), d, tmp_path)
    plate = out["plates"][0]
    assert "slice_error" not in plate, plate
    text = open(plate["gcode"]).read()
    assert "M104 S255" in text and "M190 S80" in text  # PETG temperatures
    xy = [(float(x), float(y)) for x, y in re.findall(r"^G1 [^;\n]*X([-\d.]+) Y([-\d.]+)", text, re.M)]
    assert xy and all(0 <= x <= 235 and 0 <= y <= 235 for x, y in xy)
    assert plate["filament_g"] > 0 and out["total"]["print_hours"] > 0
