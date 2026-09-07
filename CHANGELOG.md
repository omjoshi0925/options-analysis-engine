# Changelog

## 3.0.0 - 2026-09-07

- Add continuous regular-session polling, Tradier production market-data support,
  quote timestamp checks, and optional Yahoo research archives.
- Persist raw snapshots, deduplicated SQLite observations, failure diagnostics,
  heartbeat, throttling deadlines, and quality exclusions across restarts.
- Add hard worker deadlines, orphan recovery, corruption quarantine, disk-space
  checks, process locks, and macOS launchd service helpers.
- Learn a volatility adjustment from prior sessions; evaluate chronologically with
  gaps, fresh holdouts, baseline/incumbent gates, and observed strike-shape checks.
- Add model versions, checksum verification, rollback, scoring, and monitoring.
- Add a Collection & training dashboard tab and provider/service methodology docs.
- Remove public-facing personal credits and four inherited formula image assets;
  retain the existing MIT copyright/license notice for the adapted source.
- Bound NumPy below 2.4 for the validated pandas 2.x runtime; the initial NumPy
  2.5.3 validation emitted timedelta deprecation warnings.

No market-trained model is shipped. The real Yahoo probe was rate limited;
Tradier acquisition is verified with fixtures and still needs local credentials.

## 2.0.0 - 2026-09-07

The original calculator was a single Streamlit script with no empirical pipeline.
The revised version adds a shared pricing package and documented research workflow.

- Correct the displayed Delta and selected-option Greek behavior.
- Add continuous dividends, stable pricing, exact limiting prices, and validation.
- Verify all five derivatives numerically and graph their behavior across four inputs.
- Add two diagnostic IV solvers with safeguarded Newton-to-Brent fallback.
- Add multi-symbol acquisition, immutable snapshots, checksums, and source provenance.
- Audit quotes without conflating liquidity rejection and IV-solver failure.
- Compare independent constant volatility with midpoints; retain solver reconstruction
  as a numerical diagnostic and record percentage-metric denominators.
- Add grouped metrics, smiles, surfaces, parity intervals, and generated reports.
- Add an offline synthetic demonstration, 73 tests, and CI configuration.
- Preserve the upstream MIT license and document the original project's contribution.

The delivery includes no successful real-market collection: the attempted Yahoo
request was rate limited for all requested assets. See docs/VALIDATION.md.
