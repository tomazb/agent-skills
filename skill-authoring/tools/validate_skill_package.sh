#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: '$PYTHON_BIN' was not found. Install Python 3.9+ or set PYTHON_BIN." >&2
  exit 127
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "error: Python 3.9+ is required (found: $("$PYTHON_BIN" --version 2>&1))." >&2
  exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/validate_skill_package.py"
