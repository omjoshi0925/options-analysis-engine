#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
action="${1:-status}"
config_path="${2:-$project_dir/config/collector.json}"
label="com.omjoshi.options-analysis-engine.collector"
service_target="gui/$(id -u)/$label"
plist_path="$HOME/Library/LaunchAgents/$label.plist"
if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'This helper uses macOS launchd. On Linux run: bash scripts/run_collector.sh\n' >&2
  exit 1
fi
case "$action" in
  start)
    "$project_dir/.venv/bin/python" - "$project_dir" "$config_path" "$plist_path" "$label" <<'PY'
from pathlib import Path
import plistlib,sys
from options_engine.live_config import LiveConfig
project,config,plist_path=map(Path,sys.argv[1:4])
cfg,root=LiveConfig.load(config)
token=Path.home()/'.config/options-analysis-engine/tradier-token'
if cfg.provider=='tradier' and not token.is_file():
    raise SystemExit('Run bash scripts/set_tradier_token.sh before starting the background Tradier service.')
root.mkdir(parents=True,exist_ok=True)
plist_path.parent.mkdir(parents=True,exist_ok=True)
contents=dict(Label=sys.argv[4],ProgramArguments=['/bin/bash',str(project/'scripts/run_collector.sh'),str(config.resolve())],
              WorkingDirectory=str(project),RunAtLoad=True,KeepAlive={'SuccessfulExit':False},ThrottleInterval=60,
              StandardOutPath=str(root/'service.stdout.log'),StandardErrorPath=str(root/'service.stderr.log'))
with plist_path.open('wb') as stream:
    plistlib.dump(contents,stream)
PY
    if launchctl print "$service_target" >/dev/null 2>&1; then
      printf 'Collector service is already loaded.\n'
    else
      launchctl bootstrap "gui/$(id -u)" "$plist_path"
      printf 'Collector service installed and started. It will run at login and wait outside regular market hours.\n'
    fi
    ;;
  stop)
    launchctl bootout "$service_target"
    printf 'Collector stopped. Saved observations and models remain available.\n'
    ;;
  uninstall)
    if launchctl print "$service_target" >/dev/null 2>&1; then
      launchctl bootout "$service_target"
    fi
    rm -f "$plist_path"
    printf 'Launch agent removed. Saved data and credentials remain available.\n'
    ;;
  status)
    "$project_dir/.venv/bin/python" -m options_engine status --config "$config_path"
    ;;
  *)
    printf 'Usage: bash scripts/collector_service.sh {start|stop|status|uninstall} [config-path]\n' >&2
    exit 1
    ;;
esac
