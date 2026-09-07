# Options Analysis Engine

A research toolkit for European option pricing, continuous options-chain
collection, and chronological evaluation of a learned volatility model.

The mathematical baseline is Black-Scholes-Merton. A separate ridge model learns
the volatility adjustment from earlier observations and is evaluated on later
trading sessions. More data creates opportunities to improve the model; improvement
is measured and gated, never assumed.

## Version 3 capabilities

- European calls/puts, dividends, exact boundary prices, analytical Greeks,
  finite-difference verification, and diagnostic Brent/Newton implied volatility.
- Continuous polling during US equity regular sessions, including holiday,
  daylight-saving, and early-close handling; default cadence is 15 minutes.
- Yahoo research snapshots and a production Tradier adapter with quote timestamps.
- Hard acquisition deadlines, throttling backoff that survives restarts, process
  locking, rotating logs, free-disk checks, and recovery of complete orphan snapshots.
- Immutable raw snapshots plus a SQLite observation ledger with deduplication.
- Strict training quality: real market labels, a supported production feed,
  fresh synchronized bid/ask/spot timestamps, liquidity, and identifiable IV.
- Rolling historical training, train/validation/test separation by session,
  embargo gaps, regularization selection, held-out performance gates, model versions,
  checksum verification, rollback, and latest-batch monitoring.
- A Streamlit dashboard with a Collection & training tab and macOS service helpers.

## Quick start

Python 3.10+ is required. Commands are Bash and use your repository path.

```bash
cd ~/Documents/GitHub/options-analysis-engine && python3 -m venv .venv && source .venv/bin/activate && python -m pip install -r requirements.txt && python -m pytest -q
```

```bash
cd ~/Documents/GitHub/options-analysis-engine && source .venv/bin/activate && python -m streamlit run BSM_streamlit.py
```

## Start timestamp-verified collection and training

The Tradier adapter uses the production market-data API, which requires your own
account token and appropriate data access. It calls market-data endpoints only.
[Provider access requirements](https://docs.tradier.com/docs/market-data).

Create the configuration (this refuses to overwrite an existing config):

```bash
cd ~/Documents/GitHub/options-analysis-engine && source .venv/bin/activate && python -m options_engine init-live --provider tradier --config config/collector.json
```

Edit the tickers, risk-free rate, and dividend-yield scenarios in that file before
interpreting prices. Included rate/yield numbers are illustrative, not live estimates.
The default volatility baseline uses prior complete daily returns.

Save the token locally using a hidden prompt, then start the macOS service:

```bash
cd ~/Documents/GitHub/options-analysis-engine && bash scripts/set_tradier_token.sh && bash scripts/collector_service.sh start
```

The token file is outside the repository and has owner-only file permissions.
The collector runs at login and restarts after failures. It waits outside regular
sessions. Your Mac must be powered on, awake, logged in, and connected; use an
always-on host for collection independent of your laptop. No historical intraday
quotes are fabricated to fill downtime.

Check progress or stop the service:

```bash
cd ~/Documents/GitHub/options-analysis-engine && bash scripts/collector_service.sh status
```

```bash
cd ~/Documents/GitHub/options-analysis-engine && bash scripts/collector_service.sh stop
```

See [continuous collection](docs/CONTINUOUS_COLLECTION.md) for foreground/Linux
operation, startup/stop behavior, logs, storage, recovery, and provider limits.

## Yahoo research mode

Yahoo needs no Tradier token, but may throttle or return incomplete/delayed data.
The interface does not supply reliable bid/ask timestamps. These observations are
retained for research and excluded from strict-quality training.

```bash
cd ~/Documents/GitHub/options-analysis-engine && source .venv/bin/activate && python -m options_engine init-live --provider yahoo --config config/yahoo-collector.json && python -m options_engine collect --config config/yahoo-collector.json
```

Use Ctrl+C to stop a foreground collector. Do not run two configurations against
the same data root simultaneously. Change `data_root` for separate experiments.

## What gets trained

The learned target is log(calculated IV / independent baseline volatility).
Features include moneyness, time, historical volatility, rate/yield inputs, type,
and asset identity. Current option prices, provider IV, solved IV, and target-derived
Greeks are excluded from the input features.

Defaults require 300 qualifying observations over at least 12 completed trading
sessions. The last two sessions are untouched test data, the preceding two are
validation data, and one-session gaps separate both boundaries. Training uses
the earlier sessions from a rolling 60-session window. A deterministic sample
cap controls memory without using labels to choose observations.

Three regularization settings are compared on validation. A saved candidate
retains the exact training fit; validation/test rows are never refit into that
model. Promotion requires at least 2% lower spot-normalized RMSE than the baseline
on validation and test, at least 2% improvement versus the active model on test,
no material asset-level regression, no material drop in within-spread coverage,
and no detected strike-shape violations at the observed test nodes. Rejected
candidates leave the active model unchanged. Later attempts need fresh test sessions.

This estimates contemporary option values on later observations. It is not a
future option-return prediction system. See [learning methodology](docs/LEARNING.md).

## Commands and results

| Command | Purpose |
|---|---|
| `init-live` | Create an editable collector config |
| `collect` | Continuous collection; `--once` checks one scheduled cycle |
| `collect --probe` | One acquisition outside market hours, still respecting persisted backoff |
| `status` | Counts, training readiness, heartbeat, models, recent failures |
| `train` | Evaluate a candidate from complete prior sessions |
| `ingest` | Add an existing checksum-verified snapshot |
| `score-snapshot` | Compare a later snapshot with the active model and baseline |
| `select-model --baseline` | Return to the independent baseline |
| `select-model --model-id ID` | Roll back to a previously promoted model |
| `fetch` / `analyze` | Original one-shot Yahoo acquisition and snapshot analysis |
| `demo` | Explicitly synthetic offline demonstration |

Live state is stored under `data/live/` by default: `snapshots/`, `audits/`,
`observations.sqlite3`, `models/`, `evaluations/`, monitoring, and status/log files.
These files and local credentials/configs are excluded from Git. Back up the live
data folder regularly; the collector never uploads it automatically.

The included `examples/validation/` results are synthetic demonstrations.
The live Yahoo probe during this delivery was rate limited, and no Tradier token
was supplied here. **No market-trained model or successful live collection is
claimed in this release.** The runtime will collect and train after you configure
and start it with a working provider.

See [validation](docs/VALIDATION.md), [pricing methodology](docs/METHODOLOGY.md),
and [requirements coverage](docs/PROJECT_COVERAGE.md). License details are retained
in [LICENSE.txt](LICENSE.txt).
