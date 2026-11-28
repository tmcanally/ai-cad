import io
import json
import zipfile

from fastapi.testclient import TestClient

from aicad.server import app

client = TestClient(app)


def test_viewer_page_and_assets():
    assert "AI CAD" in client.get("/").text
    assert client.get("/static/viewer.js").status_code == 200
    assert client.get("/static/vendor/three/three.module.min.js").status_code == 200


def test_design_payload():
    data = client.get("/api/designs/hinged_box").json()
    assert {p["name"] for p in data["parts"]} == {"base", "lid", "pin"}
    lid = next(p for p in data["parts"] if p["name"] == "lid")
    assert len(lid["mesh"]["positions"]) % 3 == 0 and lid["mesh"]["indices"]
    assert data["motions"][0]["parts"] == ["lid"]
    assert data["params"]["width"] == 80


def test_params_in_query():
    q = json.dumps({"width": 100})
    data = client.get("/api/designs/hinged_box", params={"params": q}).json()
    assert data["bbox"]["max"][0] - data["bbox"]["min"][0] == 100


def test_stl_downloads():
    r = client.get("/api/designs/hinged_box/stl", params={"part": "lid"})
    assert r.status_code == 200 and len(r.content) > 84
    r = client.get("/api/designs/hinged_box/stl")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 3


def test_errors():
    assert client.get("/api/designs/nope").status_code == 404
    assert client.get("/api/designs/hinged_box", params={"params": "{bad"}).status_code == 400
    assert client.get("/api/designs/hinged_box/stl", params={"part": "nope"}).status_code == 404


def test_print_endpoint_and_downloads():
    info = client.get("/api/printers").json()
    assert info["printers"][0]["id"] == "ankermake_m5"
    r = client.post("/api/designs/hinged_box/print", json={"slice": False, "part_settings": {"lid": {"supports": "on"}}})
    assert r.status_code == 200, r.text
    data = r.json()
    lid = next(p for p in data["pieces"] if p["part"] == "lid")
    assert lid["supports"] is True
    f = client.get(data["plates"][0]["files"]["project_3mf"])
    assert f.status_code == 200 and f.content[:2] == b"PK"
    z = zipfile.ZipFile(io.BytesIO(client.get(data["zip"]).content))
    assert "PRINT-LIST.md" in z.namelist()
    assert client.post("/api/designs/hinged_box/print", json={"settings": {"filament": "wood"}}).status_code == 400
    assert client.get("/api/designs/hinged_box/print/ankermake_m5/files/..%2Fsecret").status_code == 404
