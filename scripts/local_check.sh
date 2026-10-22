#!/usr/bin/env bash
set -euo pipefail
source .venv/bin/activate
pytest -q
python -m compileall -q src
echo "Local validation passed."
