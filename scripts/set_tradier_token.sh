#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
import getpass
import os
directory = Path.home()/'.config/options-analysis-engine'
directory.mkdir(parents=True, exist_ok=True, mode=0o700)
token = getpass.getpass('Tradier production market-data token: ').strip()
if not token or any(c.isspace() for c in token):
    raise SystemExit('A nonempty token without whitespace is required.')
path = directory/'tradier-token'
flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os,'O_NOFOLLOW',0)
fd = os.open(path, flags, 0o600)
with os.fdopen(fd,'w') as stream:
    os.fchmod(stream.fileno(),0o600)
    stream.write(token)
print('Token saved locally outside the repository with owner-only file permissions.')
PY
