#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "${SCRIPT_DIR}")"

"${PYTHON}" "${ROOT}/tools/validate_skill_package.py" "$@"
