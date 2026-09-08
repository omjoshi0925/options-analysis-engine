# Results: a learned volatility adjustment on seven years of end-of-day option chains

Om Joshi, September 2026. Produced with `options_engine` 3.2.1; every number
below regenerates from the commands in the Reproducibility section.

## Summary

I evaluated a ridge-regression volatility adjustment against an independent
realized-volatility baseline on 292,018 end-of-day US option quotes (SPY, QQQ,
AAPL; February 2019 through September 2026) using rolling-origin walk-forward
evaluation with an embargo gap: 1,056 folds, one held-out session each, from
October 2020 through September 2026. The learned model priced the next unseen
session better than the baseline in 66.4% of folds, with a median per-fold
RMSE improvement of 10.4% (IQR -7.6% to +28.8%) and a positive average
improvement in all seven calendar years. Statistical significance depends on
how serial dependence across folds is treated: the textbook Diebold-Mariano
test strongly rejects equal accuracy (p = 2.5e-04), a Newey-West HAC variant
does not (p = 0.22), and a circular block bootstrap excludes zero at every
block length I tested up to six months, though with a lower bound near zero.
On the calmer single-year SPY 2023 subsample, the improvement survives
HAC-robust inference (p = 0.040). The fair one-line conclusion: the adjustment
helps consistently in sign and usefully in magnitude, and the evidence that
the average improvement differs from zero is borderline once the strong serial
dependence between folds is respected.

Nothing here is a forecast of option returns or a tradable claim. Losses
measure contemporaneous pricing accuracy against quoted midpoints under
maintained rate and dividend assumptions.

## Data

Quotes come from the public DoltHub database `post-no-preference/options`
(end-of-day chains with bid, ask, and implied volatility), with daily
underlying OHLC bars from `post-no-preference/stocks`. Both are freely
clonable without an account; I record the export files' SHA-256 hashes in
every snapshot's metadata. Coverage for SPY runs 2019-02-09 to 2026-09-07.

Each quote is imported into a `daily_eod` training tier: timestamps are the
verified XNYS session close (early closes included), closing-snapshot
synchrony is assumed rather than verified, and the provenance labels are
stored permanently on every row. This tier is enforced in the database itself
and never mixes with the project's strict intraday tier. The dataset publishes
no volume or open interest, so liquidity screening rests on relative spreads.
Rates and dividend yields are held constant (r = 4%; q = 1.4%, 0.6%, 0.5% for
SPY, QQQ, AAPL), which is a real limitation discussed below.

Import totals: 1,177 sessions accepted; 292,018 quotes stored; 260,296
(89.1%) passed training-quality gates. 103 candidate sessions were refused:
47 dates in 2019 that fall on non-trading days, 54 exchange holidays carrying
stale rows, and 2 sessions where the SPY underlying close was missing
(2022-08-01, 2022-09-19).

### Data-quality findings in the source

Two findings about the dataset itself came out of the calendar gate rather
than manual inspection. First, the 2019 portion of the chain table is stamped
on weekly non-trading dates (Saturdays), one snapshot per week; the importer
refused all of it rather than guess which trading day each snapshot belongs
to, which is why evaluation begins in late 2020 after 120 daily training
sessions accumulate. Second, rows dated on exchange holidays exist throughout
the table and were refused as non-sessions. Both refusals are recorded with
machine-readable reasons in the import summary.

Quote-level exclusions (31,722 rows) by recorded reason:

| Exclusion reason | Rows |
|---|---:|
| Implied volatility not identifiable / outside [3%, 300%] | 13,050 |
| Midpoint below $0.10 training floor | 11,171 |
| Outside +-35% log-moneyness band | 4,997 |
| IV unidentifiable and outside moneyness band | 1,957 |
| Midpoint floor and moneyness band | 523 |
| IV range and moneyness band | 24 |

## Method

The baseline prices every option with Black-Scholes-Merton using a 60-session
close-to-close realized volatility of the underlying, computed from strictly
prior sessions. The model is a ridge regression on log(IV / baseline sigma)
with features in log-moneyness (linear, squared, cubed, and square-root-time
interactions), maturity, log baseline volatility, carry terms (rT, qT), an
option-type indicator, and symbol identity; its predicted volatility is fed
back through the same pricing formula. The ridge penalty is re-selected inside
every fold on the last two sessions of that fold's training window.

Walk-forward specification: rolling 250-session training window, minimum 120
sessions, one-session embargo gap between training and evaluation, one fold
per evaluated session. Per-quote losses are squared spot-normalized pricing
errors against the quoted midpoint; they are averaged to one loss per session
before any statistic is computed, because quotes within a session are strongly
dependent. Inference on the session-level loss differential (baseline minus
model; positive favors the model) uses three tools: the Diebold-Mariano test
with the Harvey-Leybourne-Newbold small-sample correction and its textbook
lag-0 variance for one-step evaluation; the same test with a Newey-West
(Bartlett) HAC variance at 15 lags; and a circular block bootstrap of the mean
differential.

## Results

Full history (1,056 folds, 2020-10-23 to 2026-09-04):

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.664 |
| Mean session RMSE, baseline / model | 0.00704 / 0.00407 |
| Mean RMSE improvement | 42.2% |
| Median per-fold RMSE improvement (IQR) | 10.4% (-7.6% to 28.8%) |
| Mean loss differential | 4.50e-04 |
| DM (HLN, lag 0) | 3.67, p = 2.5e-04 |
| DM (Newey-West, 15 lags) | 1.23, p = 0.22 |
| Lag-1 autocorrelation of the differential | 0.87 |
| Block bootstrap 95% CI (block 10) | [1.00e-05, 1.19e-03] |

The 42.2% mean improvement is dominated by late 2020, where baseline errors
were enormous; the median (10.4%) is the representative figure. By calendar
year:

| Year | Folds | Win rate | RMSE improvement |
|---|---:|---:|---:|
| 2020 (Oct-Dec) | 28 | 0.71 | 88.5% |
| 2021 | 148 | 0.55 | 6.3% |
| 2022 | 144 | 0.68 | 13.8% |
| 2023 | 146 | 0.57 | 4.2% |
| 2024 | 174 | 0.66 | 9.1% |
| 2025 | 249 | 0.71 | 29.3% |
| 2026 (through Sep) | 167 | 0.76 | 20.5% |

The improvement is positive in every year and largest in high-volatility
regimes; the 2020 figure is a 28-fold estimate from a single quarter and
should be read accordingly.

Single-year SPY 2023 (83 folds, expanding window, 60-session minimum): win
rate 0.687, mean RMSE improvement 16.8%, DM (HLN) 4.86 with p = 5.5e-06,
Newey-West (6 lags) 2.09 with p = 0.040, block bootstrap CI
[8.4e-07, 6.0e-06]. On this calmer subsample the result survives HAC-robust
inference at the 5% level.

## Serial dependence and what significance means here

Adjacent folds share roughly 249 of 250 training sessions, open contracts,
and volatility regime, and the measured lag-1 autocorrelation of the loss
differential is 0.87. The textbook lag-0 DM variance therefore treats 1,056
folds as far more independent evidence than they are, and I do not rely on
its p-value. Under a Newey-West variance the full-history test statistic
falls to 1.23 (p = 0.22). The circular block bootstrap, which resamples whole
blocks of consecutive sessions, excludes zero at every block length tested:

| Block length (sessions) | 95% CI for the mean differential |
|---|---|
| 10 | [1.00e-05, 1.19e-03] |
| 21 | [7.18e-06, 1.38e-03] |
| 63 | [5.05e-06, 1.33e-03] |
| 126 | [4.93e-06, 1.32e-03] |

The bootstrap and the HAC t-test disagree because the differential is heavily
right-skewed: most sessions are near zero and a minority of stress sessions
produce large positive values, which inflates the variance a t-statistic
divides by while the percentile bootstrap follows the distribution's actual
shape. The lower CI bounds are two orders of magnitude below the mean, so I
read the full-history evidence as borderline: consistent in sign, meaningful
in magnitude, not conclusively nonzero on average once dependence is
respected. The system reported this itself; the divergence between the naive
and robust tests appeared the first time the robust test ran.

## Data coverage vs evaluation window

Every figure in this section is read from the saved artifacts listed in
`docs/results/manifest.json`, which also records their SHA-256 hashes; the
import log that printed the refusal counts above was not saved.

**Raw data span.** The chain export `full_chain.csv` holds 356,936 rows on
1,280 distinct dates from 2019-02-09 to 2026-09-07, for SPY and AAPL only: the
`option_chain` table of the cloned database contains no QQQ rows, so although
QQQ is in the configuration's ticker list, no QQQ quote exists in the store,
the folds, or any figure above. The 2019 portion is stamped on weekly
non-trading dates: 47 of the 48 dates in 2019 are non-sessions (46 Saturdays
and one Sunday) carrying 6,156 rows, and the importer refused them because a
quote stamped on a non-session cannot be assigned to a trading day without
guessing, while the `daily_eod` tier requires every quote to sit at a verified
XNYS close. The only 2019 trading-day date, 2019-05-10, is the first stored
session. Outside 2019 the calendar gate refused one more Saturday
(2020-01-04) and 55 weekday exchange holidays, so 103 dates carrying 22,282
rows were refused in total. Of the 334,654 rows on trading days, 284 SPY rows
on 2022-08-01 and 2022-09-19 were dropped because the underlying export has
no SPY close on those dates (AAPL was imported for both sessions), 334,370
reached the acquisition filters, and 42,352 of those were rejected before
storage (33,795 for a relative spread above 25%, 8,457 for an invalid quote
with a wide spread, 94 invalid quotes, 6 crossed markets), leaving the 292,018
stored quotes.

**Stored sessions versus the calendar.** The store holds 1,177 sessions from
2019-05-10 to 2026-09-04. The XNYS calendar has 1,841 sessions in that span,
so 664 sessions are absent from the source: through 2024 it holds roughly
every other session, and from 2025 it is nearly complete.

| Year | XNYS sessions | Sessions in store | Evaluated folds |
|---|---:|---:|---:|
| 2019 (from May 10) | 163 | 1 | 0 |
| 2020 | 253 | 148 | 28 |
| 2021 | 252 | 148 | 148 |
| 2022 | 251 | 144 | 144 |
| 2023 | 250 | 146 | 146 |
| 2024 | 252 | 174 | 174 |
| 2025 | 250 | 249 | 249 |
| 2026 (through Sep 4) | 170 | 167 | 167 |
| Total | 1,841 | 1,177 | 1,056 |

Folds are counted in stored sessions, so a 250-session training window or a
15-lag HAC bandwidth spans more calendar time before 2025 than after.

**Evaluation window.** First evaluated session 2020-10-23, last 2026-09-04:
1,056 sessions and 236,516 evaluated quotes (the sum of `evaluation_rows` in
`folds.csv`), of which SPY 119,219 in 1,042 folds and AAPL 117,297 in 1,053
folds. The 121 stored sessions before 2020-10-23 serve only as training data,
as the 120-session minimum plus the one-session gap require.

**Per-symbol counts, whole store.** SPY: 150,436 quotes, 130,801
training-eligible, present in 1,161 sessions and absent from 16 (including
the two missing-close sessions). AAPL: 141,582 quotes, 129,495
training-eligible, present in 1,174 sessions and absent from 3. QQQ: 0.

**SPY 2023 subsample.** Its own data root holds 144 of the 249 XNYS sessions
between 2023-01-04 and 2023-12-29 (SPY only; 16,987 quotes, 14,869
training-eligible; the export's seven holiday-stamped dates were refused). The
walk-forward evaluated 83 sessions from 2023-06-12 to 2023-12-29, 8,305 quotes
in total.

**Provenance note.** Both imports ran before the 3.2.1 commits that record the
import CSV hashes in snapshot metadata and content-hash the snapshot folders,
so the snapshot `metadata.json` files carry no `source_files` entry. The
import CSV hashes, the store hashes, and the hash of every snapshot file are
recorded in `docs/results/manifest.json` instead; each snapshot's own
`raw_options.csv` hash is in its metadata, and all 1,321 match.

## Limitations

The rate and dividend assumptions are constant across a period in which the
short rate moved from near zero to above five percent. Both the baseline and
the model price under the same misspecified carry, but the model's maturity,
carry, and symbol features can partially absorb the error while the flat
baseline cannot, so part of the measured improvement is likely carry
correction rather than volatility-structure learning. Rerunning with a
time-varying risk-free rate is the single most informative robustness check
left undone. Second, the baseline is a flat volatility with no strike or
maturity structure, a deliberately weak competitor; a per-session fitted
smile (for example SVI) is the appropriate stronger benchmark. Third, the
daily_eod tier assumes the closing snapshot's bid, ask, and underlying are
synchronous, publishes no open interest, and cannot support microstructure
claims. Fourth, evaluation begins in late 2020 because the source's 2019 data
is weekly-stamped, so the COVID crash itself is in early training windows,
not in evaluation.

## Conclusion and future work

On seven years of real end-of-day data spanning multiple volatility regimes,
a small ridge-learned adjustment to a realized-volatility baseline improved
out-of-sample option pricing accuracy consistently in sign (positive in all
seven years, two-thirds of sessions) and usefully in magnitude (median 10.4%
per fold), with statistical significance that is decisive on a calm
single-year subsample and borderline over the full history under
dependence-robust inference. Planned next steps, in order of informativeness:
a time-varying risk-free rate; an SVI-per-session competitor; and feature
ablations to attribute the improvement between moneyness structure, carry
correction, and symbol effects.

## Reproducibility

Code: `options_engine` 3.2.1 (this repository), 181 offline tests, lint
clean. Data: DoltHub `post-no-preference/options` and
`post-no-preference/stocks`, cloned 2026-09-08; export queries and file
hashes are recorded in each snapshot's `metadata.json`; check the databases'
stated license before redistribution and cite the source. Pipeline:

```bash
python -m options_engine import-eod --config config/eod-full.json \
  --chain-csv full_chain.csv --underlying-csv full_underlying.csv
python -m options_engine walk-forward --config config/eod-full.json \
  --output results/full-history-v2 --min-train-sessions 120 --gap 1 \
  --window rolling --max-train-sessions 250
```

Fold-level outputs, significance JSON, and the exclusion export live under
`docs/results/`.
