import pytest


@pytest.fixture(autouse=True)
def isolated_designs(tmp_path, monkeypatch):
    """Keep test-written designs out of the real designs/ folder."""
    monkeypatch.setenv("AICAD_DESIGNS", str(tmp_path / "designs"))
    monkeypatch.setenv("AICAD_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "designs"
