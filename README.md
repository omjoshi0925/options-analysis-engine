# Options Analysis Engine

A Black-Scholes-Merton research toolkit for European call and put pricing,
analytical and numerical Greeks, implied-volatility inversion, and reproducible
options-chain diagnostics.

## What changed

- Dividend-adjusted pricing, exact expiry and zero-volatility limits, explicit
  input validation, stable tail pricing, and put-call parity diagnostics.
- Delta, Gamma, Theta, Vega, and Rho for calls and puts, with documented units.
  The original dashboard's Delta-as-call-price display error is corrected.
- Symmetric finite differences with scale-aware steps, derivative errors, and
  convergence plots over a range of step sizes.
- Brent inversion and safeguarded Newton iteration with Brent fallback,
  European bounds, residual checks, and retained failure/identifiability statuses.
- Multi-asset, multi-expiry Yahoo acquisition; raw quote/history snapshots,
  timestamps, input assumptions, acquisition failures, environment versions,
  SHA-256 checksums, and offline replay.
- Independent constant-volatility baseline using prior 60-session realized
  returns or an explicit fixed input; provider/fitted IV never enters that baseline.
- Quote audit, pricing errors, grouped MAE/RMSE/MAPE, liquidity diagnostics,
  call/put smiles, local skew statistics, and multi-expiration surfaces when supported.
- A Streamlit dashboard, command-line workflow, automated tests, and GitHub CI.

## Install and run

Python 3.10 or later is required. All commands below are Bash, with paths for
the repository shown in the supplied screenshot.

```bash
cd ~/Documents/GitHub/options-analysis-engine && python3 -m venv .venv && source .venv/bin/activate && python -m pip install -r requirements.txt
```

```bash
cd ~/Documents/GitHub/options-analysis-engine && source .venv/bin/activate && python -m pytest -q
```

```bash
cd ~/Documents/GitHub/options-analysis-engine && source .venv/bin/activate && python -m streamlit run BSM_streamlit.py
```

The dashboard has pricing, numerical-verification, and market-analysis tabs.
It can run the synthetic demonstration, read a raw snapshot CSV, or request
Yahoo quotes. Use CLI snapshots for checksum-verified, fully recorded replay.

## Reproducible offline demonstration

This is synthetic software validation, not evidence of real-market performance.
Use a new output directory per run; existing run folders are never overwritten.

```bash
cd ~/Documents/GitHub/options-analysis-engine && source .venv/bin/activate && python -m options_engine demo --output "results/demo-$(date -u +%Y%m%dT%H%M%SZ)"
```

The run writes raw synthetic inputs and metadata, analyzed contracts, filter
audits, grouped metrics, a report, Greek step studies, and PNG figures. A checked
demonstration report and figures are included under `examples/validation/`.

## Real market acquisition and replay

The numerical rate and dividend yields in this example are **illustrative scenario
inputs, not current estimates**. Set them explicitly for the observation date.
The default independent baseline is realized volatility from 60 complete prior
trading sessions, annualized with sqrt(252). Today's daily bar is excluded.

```bash
cd ~/Documents/GitHub/options-analysis-engine && source .venv/bin/activate && snapshot_dir="data/snapshots/market-$(date -u +%Y%m%dT%H%M%SZ)" && python -m options_engine fetch --tickers SPY QQQ AAPL --rate 0.04 --dividend-yields SPY=0.01 QQQ=0.005 AAPL=0.005 --expirations 3 --output "$snapshot_dir" && python -m options_engine analyze --snapshot "$snapshot_dir" --output "results/market-$(date -u +%Y%m%dT%H%M%SZ)"
```

Supply `--volatility 0.20` to `fetch` only when you intentionally want a declared
20% scenario instead of the historical-return baseline. No contract-specific
calibration is presented as independent accuracy. The default US PM-expiry
assumption is 16:00 America/New_York, adjustable with `--expiry-hour`.

To replay a chosen snapshot with different liquidity filters:

```bash
cd ~/Documents/GitHub/options-analysis-engine && source .venv/bin/activate && read -r -p "Snapshot directory: " snapshot_dir && python -m options_engine analyze --snapshot "$snapshot_dir" --min-volume 10 --min-open-interest 100 --max-relative-spread 0.25 --output "results/filtered-$(date -u +%Y%m%dT%H%M%SZ)"
```

Yahoo may rate-limit or return incomplete chains. The tool records partial
failures, saves only real observations on the fetch path, and returns a failure
status if none were acquired. It never substitutes synthetic data. The live
verification attempt for this delivery acquired no usable quotes; see
`docs/VALIDATION.md`. Actual multi-asset empirical findings remain to be collected.

## Reading the results

| Output | Purpose |
|---|---|
| `snapshot/raw_options.csv` or snapshot folder | Unfiltered observations and row-level inputs |
| `metadata.json` | Source, assumptions, acquisition errors, checksums, environment |
| `underlying_history.csv` | Captured underlying prices for baseline provenance, when fetched |
| `filter_audit.csv` | Every input row and all exclusion reasons |
| `analyzed_options.csv` | Accepted quotes, independent baseline, Greeks, IV status, residuals |
| `metrics.csv` | Pooled and grouped errors, counts, and percentage denominators |
| `market_parity.csv` | Matched call-put bid/ask parity diagnostics |
| `smile_summary.csv` | Identified IV range and descriptive local skew |
| `greek_step_study.csv` | Analytical/numerical derivatives and actual finite-difference steps |
| `REPORT.md` | Measured findings and interpretation limits |
| `plots/` | Prices, all Greeks against S/K/T/sigma, errors, smiles, and supported surfaces |

An option midpoint is not necessarily executable. Provider IV is not ground truth.
The yfinance trade timestamp is not a bid/ask timestamp. The model is European;
American exercise, discrete dividends, uncertain synchronization, and input choices
can contribute to stock/ETF residuals. See [methodology](docs/METHODOLOGY.md).

## Project map

`options_engine/core.py` holds pricing; `numerics.py` verifies derivatives;
`iv.py` inverts prices; `data.py` handles capture and filtering; `analysis.py`
builds metrics/reports; `plots.py` produces figures; `cli.py` orchestrates runs.
`BSM_streamlit.py` calls these same functions and preserves the original helper
names for compatibility. Source images are retained as legacy assets, not used
as the authoritative dividend-adjusted equations.

See [requirements coverage](docs/PROJECT_COVERAGE.md), [validation](docs/VALIDATION.md),
and [upstream attribution](THIRD_PARTY_NOTICES.md).
