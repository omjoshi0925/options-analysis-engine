# Learned volatility model and evaluation

Black-Scholes-Merton is a pricing formula, not a trainable statistical model.
Version 3 adds a separate volatility model, then passes its predicted volatility
to that formula. The target is `log(calculated_IV / baseline_sigma)`, where IV
is inverted from the observed bid/ask midpoint and the baseline is independent
of that option midpoint.

## Inputs and estimation

Features are constructed only from spot, strike, time to expiry, the configured
rate/yield, independent baseline volatility, call/put type, and asset identity.
The baseline volatility comes from the estimator named by `baseline_estimator`
in the collector config (close-to-close by default; see the methodology page).
Because it is the target's denominator, models trained under different
estimators are not comparable, and each saved model records its baseline sources.
The basis includes log moneyness through degree three, square-root and log time,
moneyness/time interactions, log baseline volatility, rate/time and yield/time
terms, type, and asset indicators. Current midpoint, provider IV, inverted IV,
and target-derived Greeks do not enter the feature matrix.

Weighted ridge regression standardizes the basis using training rows only.
The intercept is unpenalized; aggregate weight is equalized across session,
asset, and expiration groups. Regularization values 0.01, 1, and 100 are compared
on validation error. This deliberately small deterministic model provides an
auditable first trainable extension without adding a large ML runtime.

Prediction is limited to supported assets and the fitted input range with a
10% range margin. Unsupported cases fall back to the independent baseline and
are included in metrics. Log adjustments are bounded to [-1.5, 1.5]; learned
volatility is bounded to [0.03, 3]. These bounds limit extrapolation, not prove
no-arbitrage. The calculator's displayed Greeks remain analytical BSM Greeks;
this release does not report derivatives of the learned volatility surface.

## Dataset admission

The observation store retains raw data and exclusion reasons. Training additionally
requires a market-data label in both snapshot metadata and rows, the supported
Tradier production feed, fresh and reasonably synchronized bid/ask/spot timestamps,
a regular session, standard 100-share contract size, liquid valid quotes, identifiable
IV, midpoint at least 0.10, and absolute log moneyness at most 0.35. Inverted IV must
be between 0.03 and 3. Demo data and Yahoo snapshots do not qualify.

Labels and hashes provide provenance checks for records acquired by this software;
they are not cryptographic proof of provider origin for an arbitrary imported CSV.
Keep manually constructed fixtures outside the live data root.

The rolling dataset includes at most 60 completed sessions, with a deterministic
cap of 500 observations per asset per session. Sampling sorts observation IDs,
not labels. Current New York date is excluded to avoid a partially observed
session. The defaults require at least 300 eligible rows and 12 completed
sessions, with at least 50 rows in each fitted/evaluation subset.

## Chronological evaluation

For the default minimum of 12 sessions, the split is:

| Role | Sessions in chronological order |
|---|---|
| Fit model and scaling | 1–6 |
| Gap | 7 |
| Select regularization | 8–9 |
| Gap | 10 |
| Evaluate selected candidate | 11–12 |

With more sessions the fit window grows, up to the rolling-window limit; the
last six positions retain the same roles. Every contract observed on a session
belongs to that session's role. The gaps are in trading sessions, not calendar
days. This is contemporary quote estimation on later dates, not prediction of
future returns or an independent economic-profit backtest.

A candidate retains the exact training fit. Validation and test rows are never
refit into that saved model. Promotion requires:

- At least 2% lower spot-normalized RMSE than the independent baseline on both
  validation and test, and at least 2% lower test error than the incumbent.
- No more than a one-percentage-point decrease in test within-spread coverage
  versus baseline.
- No asset's test normalized RMSE more than 5% worse than baseline.
- No detected slope-bound or convexity violations across comparable observed
  test strike grids.

The last check applies to observed nodes, not the entire strike/maturity surface.
Calendar arbitrage, early exercise, and discrete dividends are not enforced.
An improvement on two test sessions is a limited deployment gate, not statistical
proof or a guarantee of future improvement. Assumed rates/yields and a misspecified
European exercise model can be absorbed by the fit.

Both accepted and rejected evaluations consume their test dates. Another attempt
needs two new complete test sessions and the configured retraining interval.
This prevents repeated selection against the same holdout. Later rolling fits
may use older evaluated sessions as historical training data; their new holdout
must remain later and fresh. Changing data labels or deleting the registry to
reuse a holdout invalidates that evaluation discipline.

## Audit, use, and rollback

Commands below run from the repository root.

Training is checked automatically once per local date when `auto_train` is true.
It waits until enough qualifying data exists. You can request the same evaluation
explicitly without weakening its gates:

```bash
source .venv/bin/activate && python -m options_engine train --config config/collector.json
```

Each evaluation saves its selected alpha, split dates, dataset fingerprint,
validation comparisons, test metrics by asset, strike-shape checks, and test-row
predictions. Models are JSON, and active model loading verifies its SHA-256 hash.
A rejected candidate remains available for inspection but cannot be activated
through the rollback command. An accepted model is used in subsequent monitoring
and snapshot scoring. Rejection leaves the active model unchanged.

```bash
source .venv/bin/activate && python -m options_engine select-model --config config/collector.json --baseline
```

To select a previously promoted version, replace the ID below with one from
`models/registry.json`:

```bash
source .venv/bin/activate && python -m options_engine select-model --config config/collector.json --model-id YOUR_PROMOTED_MODEL_ID
```

To score an archived snapshot, replace the snapshot directory with an actual later
capture and choose an output directory that does not yet exist:

```bash
source .venv/bin/activate && python -m options_engine score-snapshot --config config/collector.json --snapshot data/live/snapshots/YYYY-MM-DD/RUN_ID --output results/later-model-score
```

Snapshot scoring reports quality problems as well as comparisons. It does not
insert scored rows into training. A snapshot overlapping the active model's
training or evaluation period is refused. If no model is active, scoring uses the independent
baseline. Current-batch monitoring warns when normalized RMSE exceeds baseline
by more than 10%; this is an operational signal, not a statistical drift test
and not an automatic rollback.

No market-trained model is shipped. All provider responses used in automated
tests are deterministic fixtures and are not empirical performance evidence.
