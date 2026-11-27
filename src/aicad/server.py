"""Local web server: serves the 3D viewer and a small JSON API around the registry."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from aicad import export, history, registry, state

VIEWER_DIR = Path(__file__).resolve().parent / "viewer"

app = FastAPI(title="AI CAD", version="0.1.0")


def _params_from_query(request: Request) -> dict[str, Any]:
    raw = request.query_params.get("params")
    if not raw:
        return {}
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"params must be JSON: {exc}") from exc
    if not isinstance(params, dict):
        raise HTTPException(400, "params must be a JSON object")
    return params


def _build(name: str, params: dict[str, Any]):
    try:
        return registry.build(name, params)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Build failed: {exc}\n{traceback.format_exc(limit=5)}") from exc


@app.get("/api/designs")
def api_designs() -> list[dict[str, Any]]:
    return [d.to_dict() for d in registry.list_designs()]


@app.get("/api/current")
def api_current() -> JSONResponse:
    return JSONResponse(state.get_current() or {})


@app.get("/api/designs/{name}")
def api_design(name: str, request: Request) -> JSONResponse:
    design, resolved = _build(name, _params_from_query(request))
    payload = design.to_viewer_json()
    payload["params"] = resolved
    info = registry.get_info(name)
    payload["info"] = info.to_dict()
    payload["saved_params"] = registry.resolve_params(info, registry.saved_params(info))
    return JSONResponse(payload)


# ---------- history and saved values (the same operations Claude has over MCP) ----------


def _changed(name: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Tell the viewer (and any other open viewer) what is current now."""
    _, resolved = _build(name, {})
    st = state.set_current(name, resolved)
    return {"version": meta["version"], "note": meta.get("note", ""), "params": resolved, "state_version": st["version"]}


def _history_call(fn, *args):
    try:
        return fn(*args)
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'\"")) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/designs/{name}/versions")
def api_versions(name: str) -> list[dict[str, Any]]:
    _history_call(registry.get_path, name)
    return list(reversed(history.list_versions(name)))


@app.post("/api/designs/{name}/params")
def api_save_params(name: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    params = body.get("params")
    if not isinstance(params, dict):
        raise HTTPException(400, "Body must be {\"params\": {...}}")
    meta = _history_call(history.save_params, name, params, body.get("note", ""))
    return _changed(name, meta)


@app.delete("/api/designs/{name}/params")
def api_clear_params(name: str) -> dict[str, Any]:
    return _changed(name, _history_call(history.clear_params, name))


@app.post("/api/designs/{name}/restore/{version}")
def api_restore(name: str, version: int) -> dict[str, Any]:
    return _changed(name, _history_call(history.restore, name, version))


@app.post("/api/designs/{name}/undo")
def api_undo(name: str) -> dict[str, Any]:
    return _changed(name, _history_call(history.undo, name))


@app.get("/api/designs/{name}/stl")
def api_stl(name: str, request: Request, part: str | None = Query(None)) -> Response:
    design, _ = _build(name, _params_from_query(request))
    if part:
        try:
            data = export.part_stl_bytes(design, part)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        filename, media = f"{design.name}-{part}.stl", "model/stl"
    else:
        data = export.stl_zip_bytes(design)
        filename, media = f"{design.name}-stl.zip", "application/zip"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(VIEWER_DIR / "index.html")


app.mount("/static", StaticFiles(directory=VIEWER_DIR), name="static")
