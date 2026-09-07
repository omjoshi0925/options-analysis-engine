#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config_path="${1:-$project_dir/config/collector.json}"
token_file="$HOME/.config/options-analysis-engine/tradier-token"
if [[ -f "$token_file" && -z "${TRADIER_TOKEN:-}" ]]; then
  export TRADIER_TOKEN
  TRADIER_TOKEN="$(cat "$token_file")"
fi
cd "$project_dir"
exec "$project_dir/.venv/bin/python" -m options_engine collect --config "$config_path"
