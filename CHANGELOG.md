# Changelog

## 3.2.1 - 2026-09-08

Fixes from external code review, all covered by new tests:

- The training tier is now pinned in the database itself: the first ingest
  records the tier in store metadata and every later ingest must match, so two
  configs pointing at one data root can no longer mix strict and daily_eod
  observations.
- EOD snapshot folders are now content-hashed, so re-importing a corrected or
  extended export for an existing date creates an immutable revision instead of
  being silently shadowed by the earlier snapshot.
- A zero-variance Diebold-Mariano differential is now reported as degenerate
  (no statistic, no p-value) instead of p=0; the significance report also adds
  a Newey-West HAC variant and the differential's lag-1 autocorrelation so
  serial correlation in session losses is visible rather than assumed away.
- Imports record the source CSV paths and SHA-256 hashes in every snapshot's
  metadata, and the import summary reports the first and last session imported.
- Walk-forward folds now include per-symbol session losses for multi-symbol
  runs.

## 3.2.0 - 2026-09-07

- Add a daily_eod training tier for free historical end-of-day chains: quotes
  are stamped at the verified XNYS session close, provenance is labeled
  (`dolt_eod` / `historical_eod`), and the strict and EOD tiers are validated
  as mutually exclusive per data root.
- Add an `import-eod` command for CSV exports of the public DoltHub
  `post-no-preference/options` database (underlying bars from
  `post-no-preference/stocks`), with per-session immutable snapshots,
  baselines computed from strictly prior sessions only, deduplicated
  re-imports, and recorded skip reasons. No account or payment is required
  for the source data; its license should be checked before publication.
- Add rolling-origin walk-forward evaluation with per-fold hyperparameter
  reselection, an embargo gap, session-level loss aggregation, the
  Diebold-Mariano test with the Harvey-Leybourne-Newbold correction, and a
  circular block bootstrap confidence interval, exposed as a `walk-forward`
  command producing folds.csv, significance.json, and a report.
- Restore the `export` command writing stored observations (optionally with
  exclusion reasons) to CSV.
- Document the tier design and workflow in docs/EOD_RESEARCH.md.

The strict tier, the promotion gates, and all 3.1 behavior are unchanged. No
market data ships in this release; the importer and walk-forward are verified
with deterministic fixtures end to end.

## 3.1.0 - 2026-09-07

- Add a Cox-Ross-Rubinstein binomial tree for American and European exercise
  with the early-exercise premium, exercise boundary, and tree Greeks; every
  analyzed quote now carries an American baseline price and premium.
- Add antithetic Monte Carlo pricing with a standard error and z-score as a
  third independent check on the closed form.
- Add Parkinson, Garman-Klass, Rogers-Satchell, and Yang-Zhang realized
  volatility estimators, selectable in the collector config, the fetch
  command, and the dashboard; close-to-close remains the default.
- Add implied forward, rate, and dividend yield from put-call parity per
  asset and expiry, reported against the assumed inputs.
- Add a strategy builder with fourteen presets, exact breakevens and bounds,
  closed-form marks, aggregated Greeks, and payoff figures.
- Add `price`, `iv`, and `strategy` commands with JSON output.
- Add dashboard sections for the tree, Monte Carlo, the parity fit, and the
  premium, plus a Strategies tab.
- Add Docker, compose, and systemd deployment with documentation.
- Add a Makefile, ruff configuration, a CI lint job, Python 3.13 in the test
  matrix, Dependabot, contribution and security policies, issue and
  pull-request templates, and a citation file.
- Regenerate the synthetic validation example with the new diagnostics.

The European baseline, its error metrics, the training features, and the
promotion gates are unchanged. No market-trained model is shipped, and no
live collection is claimed in this release.

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
