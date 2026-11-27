#!/usr/bin/env bash
# One-command setup for AI CAD on macOS or Linux.
#
#   ./setup.sh             install everything, run the tests, then open the viewer
#   ./setup.sh --no-serve  install and test only
#
# Needs about 2 GB of free disk (build123d's OpenCascade kernel is large).
set -euo pipefail
cd "$(dirname "$0")"

SERVE=1
for arg in "$@"; do
  case "$arg" in
    --no-serve) SERVE=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg"; exit 2 ;;
  esac
done

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# 1. Disk space check (df -Pk works the same on macOS and Linux).
avail_kb=$(df -Pk . | awk 'NR==2 {print $4}')
if [ "${avail_kb:-0}" -lt 2500000 ]; then
  echo "Warning: only $((avail_kb / 1024)) MB free here. AI CAD needs about 2 GB (Python + OpenCascade)."
  echo "Free some space and run ./setup.sh again, or press Enter to try anyway."
  read -r _ || true
fi

# 2. uv (fast Python package manager). It also installs the right Python for us.
if ! command -v uv >/dev/null 2>&1; then
  say "Installing uv (https://docs.astral.sh/uv/)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

# 3. Python 3.12 + dependencies into ./.venv (nothing is installed system-wide).
say "Installing Python and dependencies into .venv"
uv sync

# 4. Smoke test: the test suite builds the demo, checks the joints and exports STL.
say "Running tests"
uv run pytest -q

say "Exporting the demo box to exports/hinged_box/"
uv run aicad export hinged_box

cat <<EOF

AI CAD is ready.

  Viewer:      uv run aicad serve --open      (http://127.0.0.1:8765)
  Export STL:  uv run aicad export hinged_box --param width=100

Use it from Claude Code:
  claude mcp add aicad -- uv --directory "$PWD" run aicad mcp

Use it from Claude Desktop: add this to
~/Library/Application Support/Claude/claude_desktop_config.json under "mcpServers":
  "aicad": { "command": "$(command -v uv)", "args": ["--directory", "$PWD", "run", "aicad", "mcp"] }

EOF

if [ "$SERVE" = 1 ]; then
  say "Starting the viewer (Ctrl+C to stop)"
  exec uv run aicad serve --open
fi
