# Changelog

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
