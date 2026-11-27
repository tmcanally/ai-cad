import struct

from aicad import export, registry


def test_write_stls(tmp_path):
    design, _ = registry.build("hinged_box")
    paths = export.write_stls(design, tmp_path)
    assert [p.name for p in paths] == ["hinged_box-base.stl", "hinged_box-lid.stl", "hinged_box-pin.stl"]
    for p in paths:
        data = p.read_bytes()
        (triangles,) = struct.unpack("<I", data[80:84])  # binary STL header
        assert triangles > 10
        assert len(data) == 84 + 50 * triangles
