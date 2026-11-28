"""The describe-then-refine loop: versions, undo, saved values and the parameter check."""

from fastapi.testclient import TestClient

from aicad import history, mcp_server, registry
from aicad.server import app

V1 = '''
from build123d import *
from aicad.design import Design, Param, Part

PARAMS = {
    "width": Param(30, 10, 100, description="Width"),
    "height": Param(10, 5, 50, description="Height"),
}

def build(width=30, height=10):
    return Design(name="plate", parts=[Part("plate", Box(width, width / 2, height))])
'''

# Shape change: adds a hole and a new parameter for it.
V2 = V1.replace(
    '"height": Param(10, 5, 50, description="Height"),',
    '"height": Param(10, 5, 50, description="Height"),\n    "hole": Param(5, 1, 10, description="Hole diameter"),',
).replace(
    "def build(width=30, height=10):\n    return Design(name=\"plate\", parts=[Part(\"plate\", Box(width, width / 2, height))])",
    "def build(width=30, height=10, hole=5):\n    return Design(name=\"plate\", parts=[Part(\"plate\", Box(width, width / 2, height) - Cylinder(hole / 2, height))])",
)


def size(result, i=0):
    return result["parts"][i]["size_mm"]


def test_write_records_versions_with_notes():
    assert mcp_server.write_design("plate", V1, note="First try")["version"] == 1
    assert mcp_server.write_design("plate", V2, note="Added a hole")["version"] == 2
    notes = [v["note"] for v in history.list_versions("plate")]
    assert notes == ["First try", "Added a hole"]


def test_failed_build_is_not_a_version():
    mcp_server.write_design("plate", V1)
    out = mcp_server.write_design("plate", "def build():\n    return 1/0\n")
    assert "error" in out
    assert len(history.list_versions("plate")) == 1


def test_set_params_persists_and_survives_a_rewrite():
    mcp_server.write_design("plate", V1)
    out = mcp_server.set_params("plate", {"height": 25})
    assert size(out)[2] == 25
    assert out["version"] == 2
    # A fresh build with no overrides (viewer reload) keeps the saved value.
    _, resolved = registry.build("plate")
    assert resolved["height"] == 25
    # Claude rewrites the shape: the saved height still applies, the new param gets its default.
    out = mcp_server.write_design("plate", V2, note="Added a hole")
    assert out["params"] == {"width": 30, "height": 25, "hole": 5}


def test_set_params_rejects_unknown_names():
    mcp_server.write_design("plate", V1)
    assert "Unknown parameters" in mcp_server.set_params("plate", {"depth": 3})["error"]


def test_undo_steps_back_repeatedly_and_restores_values():
    mcp_server.write_design("plate", V1, note="v1")
    mcp_server.set_params("plate", {"width": 50})
    mcp_server.write_design("plate", V2, note="hole")

    out = mcp_server.undo_design("plate")  # back to v2: V1 source, width 50
    assert "hole" not in out["params"] and out["params"]["width"] == 50
    out = mcp_server.undo_design("plate")  # back to v1: width 30
    assert out["params"]["width"] == 30
    assert "error" in mcp_server.undo_design("plate")  # nothing before v1

    out = mcp_server.restore_version("plate", 3)
    assert out["params"]["hole"] == 5 and out["params"]["width"] == 50
    assert "hole" in mcp_server.read_design_source("plate")


def test_first_tracked_change_keeps_the_untracked_file(isolated_designs):
    registry.save_design("plate", V1)  # written before history existed
    mcp_server.write_design("plate", V2)
    versions = history.list_versions("plate")
    assert versions[0]["note"] == "Before history was kept"
    mcp_server.undo_design("plate")
    assert "hole" not in (isolated_designs / "plate.py").read_text()


def test_saved_values_for_builtin_designs():
    out = mcp_server.set_params("hinged_box", {"width": 120})
    assert out["params"]["width"] == 120
    assert not (registry.designs_dir() / "hinged_box.py").exists()  # no copy of the source needed
    mcp_server.undo_design("hinged_box")
    assert registry.build("hinged_box")[1]["width"] == 80


def test_restoring_a_builtin_after_its_code_changed_keeps_the_new_code():
    # A version saved under older built-in code must not bring that code back as a
    # designs/ copy, or every later update to the built-in would be hidden behind it.
    mcp_server.set_params("hinged_box", {"width": 120})
    mcp_server.set_params("hinged_box", {"width": 100})
    first = history.list_versions("hinged_box")[0]["version"]
    old = history.history_dir("hinged_box") / str(first) / "design.py"
    old.write_text(old.read_text() + "\n# older code\n")
    history.restore("hinged_box", first)
    assert not (registry.designs_dir() / "hinged_box.py").exists()
    assert registry.get_path("hinged_box")[1]  # still the built-in


def test_parameter_check():
    clean = mcp_server.write_design("plate", V1)
    assert clean["warnings"] == []
    messy = V1.replace("Box(width, width / 2, height)", "Box(width, width / 2, height) - Cylinder(3.2, 40)").replace(
        "def build(width=30, height=10):", "def build(width=40, height=10, depth=5):"
    )
    warnings = mcp_server.write_design("plate", messy)["warnings"]
    text = "\n".join(warnings)
    assert "'width' defaults to 40" in text
    assert "'depth' is not in PARAMS" in text
    assert "3.2 (line" in text and "40 (line" in text


def test_hinged_box_follows_the_conventions():
    from aicad.checks import check_module

    path, _ = registry.get_path("hinged_box")
    warnings = check_module(registry._load_module("hinged_box", path), path.read_text())
    assert not [w for w in warnings if "PARAMS" in w or "defaults to" in w]


def test_viewer_api_save_undo_restore():
    mcp_server.write_design("plate", V1, note="v1")
    client = TestClient(app)

    data = client.get("/api/designs/plate").json()
    assert data["saved_params"] == {"width": 30, "height": 10}

    res = client.post("/api/designs/plate/params", json={"params": {"width": 60}})
    assert res.status_code == 200 and res.json()["params"]["width"] == 60
    assert client.get("/api/designs/plate").json()["saved_params"]["width"] == 60

    versions = client.get("/api/designs/plate/versions").json()
    assert [v["version"] for v in versions] == [2, 1]  # newest first
    assert versions[0]["note"] == "Set width=60"

    assert client.post("/api/designs/plate/undo").json()["params"]["width"] == 30
    assert client.post("/api/designs/plate/restore/2").json()["params"]["width"] == 60
    assert client.post("/api/designs/plate/restore/99").status_code == 404
    assert client.post("/api/designs/plate/params", json={"params": {"nope": 1}}).status_code == 400
    assert client.delete("/api/designs/plate/params").json()["params"]["width"] == 30


def test_viewer_ignores_parameters_a_design_no_longer_has():
    from fastapi.testclient import TestClient
    import json
    from aicad.server import app

    client = TestClient(app)
    r = client.get("/api/designs/roman_shade", params={"params": json.dumps({"window_width": 800, "gone_param": 3})})
    assert r.status_code == 200, r.text
    assert r.json()["params"]["window_width"] == 800


def test_reset_clears_saved_values():
    from fastapi.testclient import TestClient
    from aicad.server import app

    client = TestClient(app)
    assert client.post("/api/designs/hinged_box/params", json={"params": {"width": 77}}).status_code == 200
    assert client.get("/api/designs/hinged_box").json()["params"]["width"] == 77
    assert client.delete("/api/designs/hinged_box/params").status_code == 200
    data = client.get("/api/designs/hinged_box").json()
    assert data["params"]["width"] != 77 and data["saved_params"].get("width") != 77
