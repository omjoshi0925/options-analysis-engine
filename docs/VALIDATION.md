# Validation record

Validation date: 2026-09-07. The implementation was tested against the supplied
source archive and requirements; the user's Mac repository was not accessed.

## Automated checks

102 tests passed with `python -m pytest -q` in a fresh Python 3.12 virtual
environment (14.09 seconds, no warnings in the final run), including:

- Known call/put reference prices and five raw Greek reference values.
- Independent risk-neutral payoff integration for call/put prices, dividends,
  and positive/negative rates.
- Analytical versus numerical Greeks across maturity, moneyness, volatility,
  dividend, rate, and spot scales.
- Bounds, parity, monotonicity, tiny OTM values, boundary prices, invalid inputs,
  market unit conversion, and symmetric boundary stencils.
- Both IV methods across calls/puts and varied maturities/volatilities, explicit
  bound/expiry failures, low-Vega Newton fallback, and bracket/iteration limits.
- Fractional expiry and daylight-saving conversion, quote exclusion reasons,
  optional volume/trade-age filters, duplicates, checksums, and snapshot replay.
- Independent baseline behavior, IV-failure retention in error metrics, MAPE
  denominator rules, empty reports, and matched bid/ask parity intervals.
- Mocked provider acquisition with captured spot/history metadata and partial failure.
- Actual Streamlit AppTest execution, checking displayed Delta, switching to puts,
  and setting expiry to zero without application exceptions.

The version 3 checks additionally cover:

- Market holidays, early closes, daylight saving, and the post-open delay.
- Strict timestamp and feed quality; synthetic metadata and rows cannot qualify.
- Tradier response normalization, history caching, authentication errors, and HTTP 429.
- Snapshot replay, unchanged-quote deduplication, completed-session SQL sampling.
- A successful acquisition-to-database-to-monitor cycle using a fixture worker.
- Hard timeout termination of an actual child process; restart backoff persistence.
- Interrupted-run recovery and quarantine of corrupt snapshots without losing valid ones.
- The full raw snapshot -> SQLite -> chronological model training path.
- Exclusion of current target/quote values from model prediction features.
- Chronological split gaps, training-only fitting, fresh holdouts, promotion/rejection,
  registry checksums, approved rollback, and insufficient-data readiness status.
- Later-snapshot scoring, training/evaluation overlap rejection, baseline fallback,
  and synthetic-metadata quality reporting.

The tests run offline. CI is configured for Python 3.10 and 3.12; those remote
jobs have not been run here. Local dependency versions are recorded in
`validated-environment.json` and the demonstration snapshot metadata.

The editable package installation also succeeded. Separately, the Bash upgrade
installer was exercised against a temporary Git repository containing the previously delivered v2
source. It preserved the existing commit and an unrelated file, retained the
upstream license, created backups, copied the validated payload, removed and backed up the four
inherited images, and refused a second installation while tracked changes were
uncommitted. A modified-image fixture was also refused before any project writes.
Bash syntax checks passed for the installer and three service/token scripts. A
native macOS LaunchAgent launch has not been executed in this Linux environment.

## Retained version 2 deterministic demonstration

The demonstration has two fictional assets, three expirations, 17 strikes,
calls and puts, a declared skew, and five deliberate bad rows. Ordinary
liquidity filters also exclude some very low-priced options.

| Measured result | Value |
|---|---:|
| Raw rows | 209 |
| Accepted rows | 184 |
| Rejected rows | 25 |
| Generated figures | 12 |
| Maximum formula parity residual | 1.4211e-14 |
| Maximum Brent price residual, accepted solves | 1.2529e-10 |
| Maximum identified IV error versus generating sigma | 1.0744e-9 |

These numerical values are software-validation results on synthetic data, not
observed market accuracy. Included reports contain illustrative baseline errors
and group rankings, with prominent synthetic labels. Greek convergence figures,
market diagnostics, and a volatility surface were visually inspected for legibility.

## Real-data verification limitation

A fetch request for SPY, QQQ, and AAPL, each with three requested expirations,
was attempted on 2026-09-07. All three returned `YFRateLimitError`; Yahoo also
reported HTTP 429. No real option quotes were acquired. The recorded acquisition
failure is included as `examples/live-acquisition-failure.json`.

The example acquisition parameters were explicitly illustrative: r=0.04,
q(SPY)=0.01, q(QQQ)=0.005, q(AAPL)=0.005. They are not current rate/yield estimates.
The live provider happy path is exercised by a controlled mock, not claimed as
verified against real Yahoo responses in this environment. Retry the README fetch
command locally to create genuine market snapshots and empirical conclusions.

## Version 3 live collector probe

A real one-cycle Yahoo probe requested SPY, QQQ, and AAPL with one expiration per
asset on 2026-09-07 at 09:24 UTC. All three returned YFRateLimitError before any
option quotes were acquired. The worker exited with failure, the run ledger
recorded it, and the collector persisted a 3,600-second retry delay. The diagnostic
copy is `examples/live-collector-probe-failure.json`; its local data-root path is
redacted. The manual probe bypassed the closed-market calendar for this network
check only. Normal collection correctly recognized the holiday and the next
regular-session start delay.

No Tradier credentials were supplied here. Its successful response path was
validated using deterministic fixtures, not authenticated real-market responses.
No live dataset, trained market model, or measured empirical improvement is
included. Configure your production provider and start collection locally.
The Mac service, provider entitlement, quote freshness, and growing eligible row
counts should be verified on the target host before relying on unattended runs.

An initial validation with NumPy 2.5.3 and pandas 2.3.3 passed but emitted timedelta
deprecation warnings. The declared NumPy range was constrained below 2.4 and the
complete final suite passed without those warnings. This is a tested compatibility
bound; remote CI matrix jobs have not been claimed as executed.
