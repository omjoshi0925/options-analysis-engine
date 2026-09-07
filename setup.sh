#!/usr/bin/env bash
set -euo pipefail
# Compatibility entry point. Configuration is passed per process, not written globally.
exec python -m streamlit run BSM_streamlit.py --server.headless=true --server.address=0.0.0.0 --server.port="${PORT:-8501}"
