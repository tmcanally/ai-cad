"""Checks that keep a design fully parametric.

The point of a design file is that every dimension a person might want to
change is a named `Param`. These checks run whenever Claude writes a design
and come back as warnings, so it can fix them before you see the model:

- every `PARAMS` entry is an argument of `build()`, and the other way round,
- the defaults in `PARAMS` and in `build()`'s signature agree,
- `build()` has no bare numbers that look like dimensions (anything other
  than small counting numbers and common angles).
"""

from __future__ import annotations

import ast
import inspect
from types import ModuleType

from aicad.design import Param

# Numbers that are rarely a dimension someone wants to tune: counting and
# halving, signs, and right angles for rotations.
ALLOWED_NUMBERS = {0, 1, 2, 0.5, 90, 180, 270, 360}
MAX_LITERAL_WARNINGS = 12


def check_module(module: ModuleType, source: str) -> list[str]:
    warnings: list[str] = []
    params: dict[str, Param] = dict(getattr(module, "PARAMS", {}) or {})
    sig = inspect.signature(module.build)
    args = {
        n: p for n, p in sig.parameters.items() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }

    if not params:
        warnings.append("No PARAMS: list every dimension as a Param so it can be adjusted.")
    for key in params:
        if key not in args and not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            warnings.append(f"PARAMS has {key!r} but build() has no argument of that name.")
    for key, p in args.items():
        if key not in params:
            warnings.append(f"build() argument {key!r} is not in PARAMS, so it cannot be adjusted.")
        elif p.default is not inspect.Parameter.empty and float(p.default) != float(params[key].default):
            warnings.append(
                f"{key!r} defaults to {p.default} in build() but {params[key].default} in PARAMS; make them match."
            )
    for key, spec in params.items():
        if spec.min is not None and spec.max is not None and not spec.min <= spec.default <= spec.max:
            warnings.append(f"{key!r} default {spec.default} is outside its range {spec.min}..{spec.max}.")

    warnings += _literal_warnings(source)
    return warnings


def _literal_warnings(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    build_fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build"), None
    )
    if build_fn is None:
        return []

    # Skip strings, keyword values that are clearly not geometry, and the signature's defaults.
    skip: set[int] = set()
    for node in ast.walk(build_fn):
        if isinstance(node, ast.keyword) and node.arg in {"color", "material", "name", "label", "notes"}:
            skip.update(id(n) for n in ast.walk(node.value))
    skip.update(id(n) for n in ast.walk(build_fn.args))

    found: list[tuple[int, float]] = []
    for node in ast.walk(build_fn):
        if id(node) in skip or not isinstance(node, ast.Constant):
            continue
        v = node.value
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if abs(v) in ALLOWED_NUMBERS:
            continue
        found.append((node.lineno, v))

    if not found:
        return []
    found.sort()
    shown = ", ".join(f"{v:g} (line {line})" for line, v in found[:MAX_LITERAL_WARNINGS])
    more = f" and {len(found) - MAX_LITERAL_WARNINGS} more" if len(found) > MAX_LITERAL_WARNINGS else ""
    return [
        f"Fixed numbers in build(): {shown}{more}. If any of these is a size, gap or count someone "
        "might want to change, make it a Param; ratios and tolerances can stay."
    ]
