# Coverage of the supplied Project.pdf

| Requested capability | Implementation/evidence |
|---|---|
| S, K, T, r, sigma, q; European calls and puts | core.py; dashboard pricing inputs |
| d1/d2, discounted strike/spot, put-call parity | Core properties, dashboard table, per-row parity residual |
| Five analytical Greeks for both types | core.py, documented raw and display units |
| Greeks versus S, K, T, volatility | Four 6-panel sensitivity figures and dashboard selector |
| Numerical Greeks, absolute/relative errors, step study | numerics.py, greek_step_study.csv, convergence figure |
| Multiple symbols, expirations, strikes, calls and puts | fetch CLI, explicit multi-symbol inputs, source fields retained |
| Bid/ask midpoint, liquidity filters | data.py and full row-level filter audit |
| Brent and Newton IV, safeguards, source-IV comparison | iv.py; status/residual/iteration/provider-difference columns |
| Call/put smiles, skew, cross-expiry/asset comparisons | plots.py, smile_summary.csv; grouped per asset/type |
| Surface when data allow | Triangular interpolation within one asset/type; no extrapolation claim |
| Error and normalized error, MAE/MAPE/RMSE/median | analysis.py, metrics.csv with counts and MAPE denominator |
| Error versus moneyness, strike, time, IV, liquidity | Eight-panel diagnostic figure and fixed-bin metric tables |
| Model-assumption investigation | METHODOLOGY.md and generated REPORT.md |
| Explain best/worst performance and limitations | Measured group rankings in each generated report |
| Reproducibility beyond original prompt | Checksums, raw snapshots, history, environment, independent baseline |
| Automated mathematical and UI verification | tests/; GitHub CI configuration |

Real acquisition is implemented, and its empty/partial/error paths are tested.
The delivery's network attempt returned no usable market quotes. Therefore, the
included numerical findings are explicitly synthetic. Run the supplied fetch
command to produce the requested real-market study; no observed accuracy or
successful live collection is claimed in this delivery.

## Version 3 research extension

| Requested improvement | Implementation/evidence |
|---|---|
| Real continuous collection | Tradier production adapter; regular-session polling; local provider token required |
| Survive interruptions | SQLite WAL, worker deadlines, persisted backoff, recovery, corruption quarantine |
| Build useful history | Checksummed raw archives, unique observations, timestamp/liquidity filters |
| Train from accumulated data | Ridge log-IV adjustment; completed-session rolling dataset |
| Measure whether a model improves | Later validation/test sessions, gaps, independent baseline and incumbent gates |
| Keep improving safely | Fresh test dates, saved model versions, rejection without activation, rollback |
| Observe collection and model health | Status CLI, latest-batch metrics, Streamlit collection tab |
| Run on user's Mac | Bash configuration/token tools and LaunchAgent helper; host must stay awake |

Live provider authentication and a native macOS LaunchAgent launch remain local
verification steps. Offline fixtures validate the pipeline without being counted
as real market observations or evidence of pricing improvement.
