#!/usr/bin/env bash
# "dashboard" starts Streamlit; any other arguments go to the options_engine CLI.
set -euo pipefail
if [[ "${1:-}" == "dashboard" ]]; then
  shift
  exec python -m streamlit run BSM_streamlit.py --server.headless=true --server.address=0.0.0.0 --server.port="${PORT:-8501}" "$@"
fi
exec python -m options_engine "$@"
