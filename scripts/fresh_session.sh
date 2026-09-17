#!/usr/bin/env bash
# One fresh session of the Design D evaluation (docs/LOCK.md; Research Plan section 7, Amendments 7 to 9).
#
# The order is the protocol. Pull the option source and look for a session dated after the lock that is not yet
# scored; with none, exit quietly. Otherwise refresh the inputs that need no chain (rate, bars, distributions),
# run predict-locked, commit the prediction files, and only then export that session's chain, import it, score it,
# append the docs/FRESH_EVAL.md line, rewrite the status line, rebuild the manifest, and push. A session whose
# prediction is committed but not yet scored resumes at the import. No chain is read before the prediction for
# that session is committed; any refusal from the locked commands stops the run and is printed, never worked around.
#
#   scripts/fresh_session.sh            run
#   scripts/fresh_session.sh --dry-run  report what would run without changing anything
#
# Runs each weekday morning, after the DoltHub source has published the previous session.
set -euo pipefail
cd "$(dirname "$0")/.."
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1
PYTHON=${PYTHON:-$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python )}
CONFIG=config/v2/C3.json
IMPORT_CONFIG=config/eod-full.json
FRESH=docs/results/v2/fresh
LOG=docs/FRESH_EVAL.md
BARS=data/external/raw/full_underlying.csv
CHAINS=data/chains
PROVENANCE=data/external/PROVENANCE.md
LOCK_DATE=$($PYTHON -c "import json; print(json.load(open('docs/lock.json'))['lock_date'])")
stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[fresh $(stamp)] $*"; }
sha() { shasum -a 256 "$1" | cut -c1-64; }

if [ -n "$(git status --porcelain)" ]; then
    echo "fresh_session: the working tree is not clean; commit or stash first" >&2
    exit 2
fi
git fetch -q origin
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
    echo "fresh_session: local main differs from origin/main; reconcile first" >&2
    exit 2
fi

# 1. Source sessions after the lock date that are not yet scored. Pulling the clone reads no chain row.
(cd options && dolt pull -q > /dev/null 2>&1) || true
candidates=$(cd options && dolt sql -r csv -q "SELECT DISTINCT date FROM option_chain WHERE act_symbol IN ('SPY','AAPL') AND date > '$LOCK_DATE' ORDER BY date" | tail -n +2)
pending=()
for d in $candidates; do
    [ -f "$FRESH/scores-$d.json" ] || pending+=("$d")
done
if [ ${#pending[@]} -eq 0 ]; then
    [ $DRY_RUN -eq 1 ] && say "no source session after $LOCK_DATE is unscored; nothing to do"
    exit 0
fi
if [ $DRY_RUN -eq 1 ]; then
    say "would refresh the inputs and run, in order: ${pending[*]}"
    for d in "${pending[@]}"; do
        if [ -f "$FRESH/predictions-$d.csv" ]; then say "  $d: prediction exists, would import the chain and score"; else say "  $d: would predict, commit, import, score"; fi
    done
    exit 0
fi

# 2. Inputs that need no chain: the rate series, the bars (S_t and the RV baseline), the distribution histories.
today=$(date -u +%Y-%m-%d)
retrieved=$(stamp)
say "refreshing inputs for ${pending[*]}"
curl -sS -o data/external/raw/DGS3MO.csv "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO"
(cd stocks && dolt pull -q > /dev/null 2>&1) || true
(cd stocks && dolt sql -r csv -q "SELECT date, act_symbol, open, high, low, close FROM ohlcv WHERE act_symbol IN ('AAPL','QQQ','SPY') AND date >= '2018-06-01' ORDER BY act_symbol, date") > "$BARS"
(cd stocks && dolt sql -r csv -q "SELECT act_symbol, ex_date, amount FROM dividend WHERE act_symbol IN ('AAPL','SPY') AND ex_date >= '2017-01-01' ORDER BY act_symbol, ex_date") > data/external/raw/dolt-stocks-dividend-aapl-spy.csv
(cd stocks && dolt sql -r csv -q "SELECT act_symbol, ex_date, to_factor, for_factor FROM split WHERE act_symbol IN ('AAPL','SPY') ORDER BY act_symbol, ex_date") > data/external/raw/dolt-stocks-split-aapl-spy.csv
curl -sS -L -o data/external/raw/spdr-etf-historical-distributions.xlsx "https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx"
$PYTHON scripts/build_external_inputs.py --start 2018-01-01 --crosscheck data/external/raw/dolt-stocks-dividend-aapl-spy.csv > /dev/null
# Apple's dividend page is not retrievable without a browser, so the section 3 file is kept and the refreshed DoltHub
# dividend table is the cross-check: an ex-date there later than the issuer files' means a stale history, and the run stops.
$PYTHON - <<'EOF'
import csv
import sys
issuer = {s: max((r["ex_date"] for r in csv.DictReader(open("data/external/dividends.csv")) if r["symbol"] == s), default="") for s in ("AAPL", "SPY")}
table = {s: max((r["ex_date"] for r in csv.DictReader(open("data/external/raw/dolt-stocks-dividend-aapl-spy.csv")) if r["act_symbol"] == s), default="") for s in ("AAPL", "SPY")}
for symbol in ("AAPL", "SPY"):
    if table[symbol] > issuer[symbol]:
        sys.exit(f"fresh_session: the DoltHub dividend table lists a {symbol} ex-date {table[symbol]} after the issuer history's {issuer[symbol]}; "
                 "refresh the issuer file by hand (data/external/PROVENANCE.md sections 2 and 3) before continuing")
EOF
last_quote=$(awk -F, 'NR > 1 && $2 != "" && $2 != "." {d=$1} END {print d}' data/external/raw/DGS3MO.csv)
last_bar=$(awk -F, 'NR > 1 {if ($1 > d) d=$1} END {print d}' "$BARS")
last_aapl=$(awk -F, '$1 == "AAPL" {d=$2} END {print d}' data/external/dividends.csv)
last_spy=$(awk -F, '$1 == "SPY" {d=$2} END {print d}' data/external/dividends.csv)
printf '| %s | %s / %s | %s / %s | %s | %s / %s, %s | %s |\n' "$retrieved" "$(sha data/external/raw/DGS3MO.csv)" "$last_quote" "$(sha "$BARS")" "$last_bar" \
    "$(sha data/external/raw/spdr-etf-historical-distributions.xlsx)" "$(sha data/external/dividends.csv)" "$last_aapl" "$last_spy" "$today" >> "$PROVENANCE"
git add data/external
git commit -q -m "data: refresh inputs for the fresh session ${pending[0]} ($retrieved)"
say "inputs refreshed and committed ($(git rev-parse --short HEAD)); rate through $last_quote, bars through $last_bar"

# 3. Each pending session in date order: predict, commit, and only then read the chain.
for d in "${pending[@]}"; do
    if [ ! -f "$FRESH/predictions-$d.csv" ]; then
        if ! grep -q "^$d," "$BARS"; then
            say "the stocks source has no bar for $d yet; stopping before $d (S_t is required)"
            break
        fi
        $PYTHON -m options_engine predict-locked --session "$d" --config "$CONFIG" --underlying-csv "$BARS" --dividend-history-end "$today" --out-dir "$FRESH" > /dev/null
        git add "$FRESH/predictions-$d.csv" "$FRESH/predictions-$d.json"
        git commit -q -m "fresh: predictions for $d"
        say "predicted $d and committed ($(git rev-parse --short HEAD))"
    fi
    git ls-files --error-unmatch "$FRESH/predictions-$d.csv" > /dev/null
    mkdir -p "$CHAINS"
    (cd options && dolt sql -r csv -q "SELECT date, act_symbol, expiration, strike, call_put, bid, ask, vol FROM option_chain WHERE act_symbol IN ('SPY','AAPL') AND date = '$d'") > "$CHAINS/fresh_chain_$d.csv"
    $PYTHON -m options_engine import-eod --config "$IMPORT_CONFIG" --chain-csv "$CHAINS/fresh_chain_$d.csv" --underlying-csv "$BARS" > /dev/null
    $PYTHON -m options_engine score-locked --session "$d" --config "$CONFIG" --predictions-dir "$FRESH" --log "$LOG" > /dev/null
    git add "$FRESH/scores-$d.json" "$LOG"
    git commit -q -m "fresh: scores for $d"
    say "scored $d ($(git rev-parse --short HEAD)): $(tail -1 "$LOG")"
done

# 4. Status line, manifest, push.
$PYTHON - "$today" <<'EOF'
import re
import sys
from pathlib import Path
today = sys.argv[1]
log = Path("docs/FRESH_EVAL.md")
text = log.read_text()
sessions = re.findall(r"^\| (\d{4}-\d{2}-\d{2}) \|", text, re.M)
span = sessions[0] if len(sessions) == 1 else f"{sessions[0]} to {sessions[-1]}"
line = (f"Sample rule status ({today}): {len(sessions)} of 60 sessions scored ({span}); no inference before the rule is met. XNYS holds 135 "
        "sessions from 2026-09-16 to 2027-03-31. At roughly 0.64 source sessions per weekday (the whole-span rate, 1,177 of 1,841 XNYS sessions) "
        "about 86 sessions are expected by the 2027-03-31 cutoff and the 60th around 2027-01-29, so the 60-session limb is expected to close the "
        "sample first; at the last twelve months' rate (0.99) about 133 and the 60th around 2026-12-10. Sixty become unreachable by the cutoff at "
        "0.64 per session only if fewer than 60 minus 0.64 times the sessions remaining have arrived. This line is written by "
        "scripts/fresh_session.sh; the table below is written only by `score-locked`.")
new, count = re.subn(r"^Sample rule status \(.*?\): .*?written only by `score-locked`\.$", line, text, count=1, flags=re.M | re.S)
if count != 1:
    sys.exit("fresh_session: the sample rule status line was not found in docs/FRESH_EVAL.md")
log.write_text(new)
EOF
$PYTHON docs/results/build_manifest.py > /dev/null
$PYTHON docs/results/build_manifest.py --check > /dev/null
git add "$LOG" docs/results/manifest.json
git commit -q -m "docs(results): fresh-evaluation status and manifest after ${pending[*]}"
git push -q origin main
say "pushed $(git rev-parse --short HEAD)"
