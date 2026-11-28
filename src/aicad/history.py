"""Version history, undo and saved parameter values for designs.

Every accepted change to a design (new source from Claude, saved parameter
values, a restore) becomes a numbered version under
`designs/.history/<name>/<n>/`, holding a copy of the source, the saved
parameter values and a short note saying what changed. Restoring a version
copies it back and records that as a new version, so nothing is ever lost.

Saved parameter values live next to the design in `designs/<name>.params.json`
and override the defaults written in the design file. That way a value you
or Claude set survives a reload, and survives Claude rewriting the design.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from aicad import registry


def params_path(name: str) -> Path:
    return registry.designs_dir() / f"{name}.params.json"


def history_dir(name: str) -> Path:
    return registry.designs_dir() / ".history" / name


# ---------------------------------------------------------------- saved values


def load_saved_params(name: str) -> dict[str, float]:
    try:
        data = json.loads(params_path(name).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}


def _write_saved_params(name: str, params: dict[str, float]) -> None:
    path = params_path(name)
    if params:
        path.write_text(json.dumps(params, indent=2, sort_keys=True) + "\n")
    else:
        path.unlink(missing_ok=True)


def save_params(name: str, params: dict[str, Any], note: str = "") -> dict[str, Any]:
    """Merge `params` into the design's saved values and record a version.

    Values are checked and clamped against the design's PARAMS first, so an
    unknown name raises ValueError instead of being stored.
    """
    info = registry.get_info(name)
    ensure_baseline(name)
    merged = {**registry.saved_params(info), **params}
    resolved = registry.resolve_params(info, merged)
    _write_saved_params(name, resolved)
    if not note:
        note = "Set " + ", ".join(f"{k}={_fmt(resolved[k])}" for k in params if k in resolved)
    return snapshot(name, note)


def clear_params(name: str, note: str = "Reset parameters to the design's defaults") -> dict[str, Any]:
    ensure_baseline(name)
    _write_saved_params(name, {})
    return snapshot(name, note)


# ---------------------------------------------------------------- versions


def _version_dirs(name: str) -> list[Path]:
    d = history_dir(name)
    if not d.exists():
        return []
    return sorted((p for p in d.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name))


def _read_meta(vdir: Path) -> dict[str, Any]:
    meta = json.loads((vdir / "meta.json").read_text())
    meta["version"] = int(vdir.name)
    return meta


def list_versions(name: str) -> list[dict[str, Any]]:
    """Oldest first: version number, time, note, and the parameter values saved with it."""
    out = []
    for vdir in _version_dirs(name):
        meta = _read_meta(vdir)
        try:
            meta["params"] = json.loads((vdir / "params.json").read_text())
        except FileNotFoundError:
            meta["params"] = {}
        out.append(meta)
    return out


def snapshot(name: str, note: str, restored_from: int | None = None) -> dict[str, Any]:
    """Record the design's current source and saved values as the next version."""
    path, _ = registry.get_path(name)
    dirs = _version_dirs(name)
    n = int(dirs[-1].name) + 1 if dirs else 1
    vdir = history_dir(name) / str(n)
    vdir.mkdir(parents=True)
    shutil.copyfile(path, vdir / "design.py")
    (vdir / "params.json").write_text(json.dumps(load_saved_params(name), indent=2, sort_keys=True))
    meta: dict[str, Any] = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "note": note}
    if restored_from is not None:
        meta["restored_from"] = restored_from
    (vdir / "meta.json").write_text(json.dumps(meta, indent=2))
    meta["version"] = n
    return meta


def ensure_baseline(name: str) -> None:
    """Before the first tracked change, record what is there now so it can be undone."""
    try:
        registry.get_path(name)
    except KeyError:
        return  # brand-new design: nothing to keep
    if not _version_dirs(name):
        snapshot(name, "Before history was kept")


def restore(name: str, version: int) -> dict[str, Any]:
    """Make `version` the current design again (source and saved values), as a new version."""
    vdir = history_dir(name) / str(int(version))
    if not (vdir / "design.py").exists():
        have = [v["version"] for v in list_versions(name)]
        raise KeyError(f"{name} has no version {version}. Versions: {have}")
    source = (vdir / "design.py").read_text()
    path, _ = registry.get_path(name)
    if path.read_text() != source:
        registry.save_design(name, source)  # built-ins get a user copy in designs/
    _write_saved_params(name, json.loads((vdir / "params.json").read_text()))
    note = _read_meta(vdir).get("note", "")
    return snapshot(name, f"Restored version {version}" + (f" ({note})" if note else ""), restored_from=int(version))


def undo(name: str) -> dict[str, Any]:
    """Step back one version. Repeating it keeps stepping back, rather than undoing the undo."""
    versions = list_versions(name)
    if not versions:
        raise ValueError(f"{name} has no history to undo.")
    latest = versions[-1]
    position = latest.get("restored_from", latest["version"])
    if position <= 1:
        raise ValueError(f"{name} is already at its first version.")
    return restore(name, position - 1)


def _fmt(v: float) -> str:
    return f"{v:g}"
