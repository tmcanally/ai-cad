import asyncio

from aicad import mcp_server, state

GOOD = '''
from build123d import *
from aicad.design import Design, Param, Part

PARAMS = {"size": Param(20, 5, 50)}

def build(size=20):
    return Design(name="cube", parts=[Part("cube", Box(size, size, size))])
'''


def call(tool, args):
    return asyncio.run(mcp_server.mcp.call_tool(tool, args))


def test_tools_registered():
    tools = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"list_designs", "read_design_source", "write_design", "build_design", "export_stl"} <= tools


def test_build_design_sets_viewer_state():
    out = mcp_server.build_design("hinged_box", {"width": 100})
    assert out["params"]["width"] == 100
    assert state.get_current()["name"] == "hinged_box"


def test_write_build_and_export_user_design(tmp_path, isolated_designs):
    out = mcp_server.write_design("cube", GOOD)
    assert "error" not in out, out
    assert out["parts"][0]["size_mm"] == [20, 20, 20]
    assert (isolated_designs / "cube.py").exists()
    files = mcp_server.export_stl("cube", {"size": 10}, str(tmp_path / "out"))["files"]
    assert len(files) == 1


def test_write_design_reports_errors():
    out = mcp_server.write_design("broken", "def build():\n    return 1/0\n")
    assert "ZeroDivisionError" in out["traceback"]


def test_call_tool_over_protocol_layer():
    result = call("list_designs", {})
    assert result is not None
