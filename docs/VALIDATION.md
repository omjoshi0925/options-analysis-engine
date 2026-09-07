# Validation record

Validation date: 2026-09-07. The implementation was tested against the supplied
source archive and requirements; the user's Mac repository was not accessed.

## Automated checks

73 tests passed with `python3 -m pytest -q`, including:

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

The tests run offline. CI is configured for Python 3.10 and 3.12; those remote
jobs have not been run here. Local dependency versions are recorded in
`validated-environment.json` and the demonstration snapshot metadata.

The editable package installation also succeeded. Separately, the Bash upgrade
installer was exercised against a temporary Git repository containing the original
source. It preserved the existing commit and an unrelated file, retained the
upstream license, created backups, copied the validated payload, and refused a
second installation while tracked changes were uncommitted.

## Deterministic demonstration

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
