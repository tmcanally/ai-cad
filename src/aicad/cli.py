"""Command line: `aicad serve`, `aicad mcp`, `aicad list`, `aicad export`."""

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


if __name__ == "__main__":
    main()
