"""Find design modules and build them.

A design is any Python file that defines `build(**params) -> Design`, and
optionally `TITLE`, `DESCRIPTION` and `PARAMS` (a dict of `Param`). Built-in
examples live in `aicad/models/`; designs written by you or by Claude over
MCP live in the project's `designs/` folder (override with AICAD_DESIGNS).
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from aicad.design import Design, Param

PACKAGE_DIR = Path(__file__).resolve().parent
BUILTIN_DIR = PACKAGE_DIR / "models"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def project_root() -> Path:
    """The repo checkout (where pyproject.toml lives), or the working directory."""
    candidate = PACKAGE_DIR.parents[1]
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


def designs_dir() -> Path:
    d = Path(os.environ.get("AICAD_DESIGNS", project_root() / "designs"))
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class DesignInfo:
    name: str
    path: Path
    builtin: bool
    title: str
    description: str
    params: dict[str, Param]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "builtin": self.builtin,
            "path": str(self.path),
            "params": {k: v.to_dict() for k, v in self.params.items()},
        }


def _design_files() -> dict[str, tuple[Path, bool]]:
    found: dict[str, tuple[Path, bool]] = {}
    for builtin, folder in ((True, BUILTIN_DIR), (False, designs_dir())):
        for f in sorted(folder.glob("*.py")):
            if f.stem.startswith("_"):
                continue
            found[f.stem] = (f, builtin)  # user designs override built-ins
    return found


def _load_module(name: str, path: Path) -> ModuleType:
    """Import fresh from disk every time so edits show up without a restart."""
    mod_name = f"aicad_design_{name}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "build", None)):
        raise TypeError(f"{path.name} must define build(**params) -> Design")
    return module


def list_designs() -> list[DesignInfo]:
    out = []
    for name in _design_files():
        try:
            out.append(get_info(name))
        except Exception as exc:  # a broken user file shouldn't hide the others
            path, builtin = _design_files()[name]
            out.append(DesignInfo(name, path, builtin, name, f"(failed to load: {exc})", {}))
    return out


def get_path(name: str) -> tuple[Path, bool]:
    files = _design_files()
    if name not in files:
        raise KeyError(f"Unknown design {name!r}. Available: {sorted(files)}")
    return files[name]


def get_info(name: str) -> DesignInfo:
    path, builtin = get_path(name)
    module = _load_module(name, path)
    return DesignInfo(
        name=name,
        path=path,
        builtin=builtin,
        title=getattr(module, "TITLE", name.replace("_", " ").capitalize()),
        description=getattr(module, "DESCRIPTION", (module.__doc__ or "").strip().split("\n")[0]),
        params=dict(getattr(module, "PARAMS", {})),
    )


def resolve_params(info: DesignInfo, params: dict[str, Any] | None) -> dict[str, float]:
    """Fill defaults, coerce to numbers and clamp to each Param's limits."""
    params = dict(params or {})
    unknown = set(params) - set(info.params)
    if unknown and info.params:
        raise ValueError(f"Unknown parameters {sorted(unknown)} for {info.name}. Known: {sorted(info.params)}")
    resolved: dict[str, float] = {}
    for key, spec in info.params.items():
        value = float(params.get(key, spec.default))
        if spec.min is not None:
            value = max(spec.min, value)
        if spec.max is not None:
            value = min(spec.max, value)
        resolved[key] = value
    if not info.params:
        resolved = {k: float(v) for k, v in params.items()}
    return resolved


_cache: dict[tuple, Design] = {}


def saved_params(info: DesignInfo) -> dict[str, float]:
    """Values saved for this design (see aicad.history), limited to parameters it still has."""
    from aicad.history import load_saved_params

    saved = load_saved_params(info.name)
    return {k: v for k, v in saved.items() if k in info.params}


def build(name: str, params: dict[str, Any] | None = None) -> tuple[Design, dict[str, float]]:
    """Build a design, caching by (name, params, file modification time).

    Parameters not given fall back to the saved values, then to the design's defaults.
    """
    path, _ = get_path(name)
    info = get_info(name)
    resolved = resolve_params(info, {**saved_params(info), **(params or {})})
    key = (name, path.stat().st_mtime_ns, tuple(sorted(resolved.items())))
    if key not in _cache:
        module = _load_module(name, path)
        design = module.build(**resolved)
        if not isinstance(design, Design):
            raise TypeError(f"{name}.build() returned {type(design).__name__}, expected aicad.design.Design")
        if len(_cache) > 32:
            _cache.clear()
        _cache[key] = design
    return _cache[key], resolved


def save_design(name: str, source: str) -> Path:
    """Write a user design file (never overwrites built-ins in the package)."""
    if not NAME_RE.match(name):
        raise ValueError("Design names must be lower_snake_case, start with a letter, max 64 chars.")
    path = designs_dir() / f"{name}.py"
    path.write_text(source)
    return path
