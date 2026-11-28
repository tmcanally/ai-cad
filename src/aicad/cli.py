"""Command line: `aicad serve`, `aicad mcp`, `aicad list`, `aicad export`, `aicad print`."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from pathlib import Path


def _parse_params(items: list[str]) -> dict[str, float]:
    params = {}
    for item in items:
        key, _, value = item.partition("=")
        if not value:
            sys.exit(f"Bad --param {item!r}; use key=value, e.g. --param width=100")
        params[key] = float(value)
    return params


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="aicad", description="AI-driven CAD on build123d")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Start the 3D viewer at http://127.0.0.1:8765")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--open", action="store_true", help="Open the viewer in your browser")

    sub.add_parser("mcp", help="Run the MCP server on stdio (for Claude Desktop / Claude Code)")
    sub.add_parser("list", help="List designs")

    p_exp = sub.add_parser("export", help="Export a design to STL (one file per part)")
    p_exp.add_argument("design")
    p_exp.add_argument("--out", default=None, help="Output folder (default: exports/<design>)")
    p_exp.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")

    p_print = sub.add_parser("print", help="Orient, arrange and slice a design's printed parts (AnkerMake M5 by default)")
    p_print.add_argument("design")
    p_print.add_argument("--param", action="append", default=[], metavar="KEY=VALUE", help="Design parameter")
    p_print.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                         help="Job or all-parts setting, e.g. filament=PETG, infill=30, layer_height=0.28")
    p_print.add_argument("--part", action="append", default=[], metavar="PART.KEY=VALUE",
                         help="One part's setting, e.g. headrail_1.orientation=back or lid.supports=on")
    p_print.add_argument("--no-slice", action="store_true", help="Only write the .3mf plates, don't run the slicer")
    p_print.add_argument("--out", default=None, help="Output folder (default: exports/<design>/<printer>)")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        url = f"http://{args.host}:{args.port}"
        print(f"AI CAD viewer: {url}")
        if args.open:
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        uvicorn.run("aicad.server:app", host=args.host, port=args.port, log_level="warning")
    elif args.cmd == "mcp":
        from aicad.mcp_server import main as mcp_main

        mcp_main()
    elif args.cmd == "list":
        from aicad import registry

        for d in registry.list_designs():
            print(f"{d.name:20s} {d.title} - {d.description}")
    elif args.cmd == "export":
        from aicad import export, registry

        design, resolved = registry.build(args.design, _parse_params(args.param))
        out = Path(args.out) if args.out else registry.project_root() / "exports" / args.design
        for path in export.write_stls(design, out):
            print(path)
        print("params:", json.dumps(resolved))
    elif args.cmd == "print":
        from aicad import printing, registry

        settings = {k: _setting_value(v) for k, v in (_kv(i, "--set") for i in args.set)}
        part_settings: dict[str, dict] = {}
        for item in args.part:
            key, value = _kv(item, "--part")
            part, _, setting = key.rpartition(".")
            if not part:
                sys.exit(f"Bad --part {item!r}; use part.setting=value, e.g. lid.supports=on")
            part_settings.setdefault(part, {})[setting] = _setting_value(value)
        design, resolved = registry.build(args.design, _parse_params(args.param))
        try:
            plan = printing.plan_print(design, settings, part_settings)
        except ValueError as exc:
            sys.exit(str(exc))
        out = Path(args.out) if args.out else registry.project_root() / "exports" / args.design / plan.job.printer
        if not args.no_slice:
            print(f"Slicing {len(plan.pieces)} pieces; this can take a minute per plate...")
        summary = printing.write_print_job(plan, design, out, slice=not args.no_slice)
        print(printing.print_list_markdown(summary))
        print(f"Files in {out}")


def _kv(item: str, flag: str) -> tuple[str, str]:
    key, _, value = item.partition("=")
    if not value:
        sys.exit(f"Bad {flag} {item!r}; use key=value")
    return key.strip(), value.strip()


def _setting_value(value: str):
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


if __name__ == "__main__":
    main()
