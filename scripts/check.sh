#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ruff check .
python -m pytest -q
python docs/results/build_manifest.py --check
