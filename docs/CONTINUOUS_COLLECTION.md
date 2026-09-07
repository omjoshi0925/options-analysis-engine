# Continuous market-data collection

The collector polls option chains; it is not an exchange streaming feed. Its
15-minute default cadence is a research sampling choice. Actual availability,
quote delay, and permissions depend on the configured provider.

## Provider setup

Tradier production is the timestamp-verified adapter. It needs your account's
production API token and appropriate market-data access. Requests are restricted
to market-data GET endpoints; this project does not place orders. Tradier describes
production versus sandbox access in its [market-data documentation](https://docs.tradier.com/docs/market-data).
The [chain endpoint](https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains)
provides the bid/ask fields and quote timestamps used by the quality checks.

Create your config and save the token with a hidden prompt:

```bash
cd ~/Documents/GitHub/options-analysis-engine && source .venv/bin/activate && python -m options_engine init-live --provider tradier --config config/collector.json && bash scripts/set_tradier_token.sh
```

The token is stored outside Git at `~/.config/options-analysis-engine/tradier-token`
with owner-only permissions. It is loaded by `scripts/run_collector.sh` into
`TRADIER_TOKEN`. Unknown config keys are rejected, including credential fields.
Do not put credentials in a JSON config or commit them.

Edit `config/collector.json` before starting. Rate and dividend inputs are explicit
illustrative scenarios, not automatically updated estimates. The daily-return
volatility baseline uses prior complete days. Tradier history is retained as
returned; this release does not independently repair splits or corporate actions.
Choose assets/periods accordingly and inspect sudden baseline changes.

Yahoo is an optional archive/research provider. Missing trustworthy bid/ask quote
timestamps make Yahoo rows ineligible for this release's strict training dataset.
There is no silent fallback from a failed live provider to synthetic data.

## Scheduling and resilience

The collector uses the XNYS regular-session calendar, including holidays, daylight
saving, and early closes. It starts five minutes after the regular open and stops
new scheduled acquisitions at the close. It uses regular equity hours even for
products with extended options hours. Calendar behavior is supplied by
[exchange_calendars](https://github.com/gerrymanoim/exchange_calendars).

A process lock prevents concurrent collectors for one data root. Each acquisition
runs in a child process with a hard deadline. A hanging or failed request records
a failed run; the parent can continue on a later cycle. Exponential backoff with
jitter and provider retry delays is persisted across restarts. Tradier requests
are spaced at no more than 30 per minute in this process. This is not a shared
account-wide quota manager.

Complete snapshots are checksummed before ingestion. On restart, complete orphan
snapshots are recovered and runs interrupted by shutdown are marked. Incomplete
pending files are not treated as valid quotes. Corrupt snapshots found during
recovery are preserved in quarantine and recorded as failures, allowing other
snapshots and subsequent collection to proceed. Replaying a snapshot is idempotent.
An observation fingerprint excludes the collection timestamp: repeated unchanged
quotes do not inflate training counts. Raw archives remain available even when
individual rows are excluded from training.

The default data root is relative to the config file: `../data/live` from the
`config` directory resolves to the project's `data/live`. Separate experiments
should use separate roots. This default is ignored by Git.

| Setting | Default | Meaning |
|---|---:|---|
| interval_seconds | 900 | Delay between successful collection cycles |
| expirations | 4 | Maximum expirations requested per asset |
| request_timeout_seconds | 15 | Individual HTTP timeout |
| cycle_timeout_seconds | 180 | Hard acquisition deadline |
| max_backoff_seconds | 7200 | Exponential backoff cap; provider delays can exceed it |
| max_quote_age_seconds | 180 | Maximum bid/ask age at collection |
| max_spot_age_seconds | 120 | Maximum underlying trade age |
| max_timestamp_skew_seconds | 120 | Maximum span of bid, ask, and spot timestamps |
| min_open_interest | 25 | Liquidity threshold |
| max_relative_spread | 0.25 | Bid/ask width divided by midpoint |
| min_days / max_days | 2 / 365 | Maturity range |
| min_free_disk_mb | 500 | Acquisition is stopped below this available space |

The spot timestamp is the underlying's last trade time, not a synchronized
exchange midpoint. This makes the freshness screen conservative and can reject
illiquid assets. Qualification does not establish that an observed midpoint was
executable. US equity/ETF options use American exercise; the pricing baseline is
European and does not model early exercise or discrete dividend schedules.

## macOS service

```bash
cd ~/Documents/GitHub/options-analysis-engine && bash scripts/collector_service.sh start
```

This installs a user LaunchAgent that starts at login and restarts after a failed
exit. Your Mac must remain awake, logged in, powered on, and connected. The helper
uses the repository's `.venv`; reinstall dependencies there when upgrading.
The service is not installed or started by the upgrade installer.

```bash
cd ~/Documents/GitHub/options-analysis-engine && bash scripts/collector_service.sh status
```

```bash
cd ~/Documents/GitHub/options-analysis-engine && bash scripts/collector_service.sh stop
```

`stop` unloads the current service; the LaunchAgent file remains and can run at a
later login. To prevent that, use `uninstall`, which leaves data and credentials:

```bash
cd ~/Documents/GitHub/options-analysis-engine && bash scripts/collector_service.sh uninstall
```

After editing config, stop and start the service so it reloads the settings.
The dashboard's Collection & training tab reads the same data root and reports
heartbeat age, failures, counts, training readiness, and active model metrics.

## Foreground operation and verification

On macOS or Linux, the same collector can run in a terminal:

```bash
cd ~/Documents/GitHub/options-analysis-engine && bash scripts/run_collector.sh
```

Use Ctrl+C to stop. For operation independent of your laptop, run this command
under your host's service manager on an always-on machine. No server is deployed
by this package. A one-cycle check respects the trading calendar:

```bash
cd ~/Documents/GitHub/options-analysis-engine && source .venv/bin/activate && python -m options_engine collect --config config/collector.json --once
```

Direct CLI calls need `TRADIER_TOKEN` in the environment. The wrapper loads the
saved token automatically for continuous operation. `--probe` explicitly allows
one out-of-hours acquisition and still honors persisted backoff. Out-of-session
or stale quotes can be archived but are excluded from training.

## Storage and maintenance

- `snapshots/`: raw option chains, baseline history, metadata, and checksums.
- `observations.sqlite3`: WAL ledger, run status, unique observations, and quality reasons.
- `audits/`: derived analysis and exclusions per acquisition.
- `models/` and `evaluations/`: versioned models, registry, holdout scores, and predictions.
- `collector_status.json`, `training_status.json`, and `latest_monitor.json`: dashboard state.
- `collector.log`: rotating logs (five MB, four backups); `failures/`: acquisition diagnostics.

Provider errors are saved without tokens or response bodies. The service's
stdout/stderr logs are separate. There is no automatic deletion of raw archives,
so monitor disk usage and back up the data root. Back up while both collection and
manual training are stopped to keep the SQLite database and model registry
consistent. For the default root, a local backup sequence is:

```bash
cd ~/Documents/GitHub/options-analysis-engine && bash scripts/collector_service.sh stop && mkdir -p "$HOME/Documents/options-engine-backups" && tar -czf "$HOME/Documents/options-engine-backups/live-$(date +%Y%m%d-%H%M%S).tar.gz" -C data live && bash scripts/collector_service.sh start
```

Raw quote downtime cannot be reconstructed by restarting the collector. Do not
label repeated or synthetic data as missing historical market observations.
