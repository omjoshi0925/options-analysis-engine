# Research notebook

Dated working notes on the empirical record, in chronological order. Each
entry says what was done, what it rests on, and what could not be established.

## 2026-09-08: freezing the v1 study (tag `study-v1`)

**Scope.** Freeze the study reported in `docs/RESULTS.md` so that every
number there traces to a saved output. Code is `options_engine` 3.2.1 at
commit 5339396, the commit that added the report. No model code changed, no
walk-forward was rerun, and no number in the report was edited.

**What was frozen.** The 1,056-fold full-history walk-forward
(`results/full-history-v2`: folds.csv, significance.json, REPORT.md), the
83-fold SPY 2023 run (`results/spy-2023-v2`), the earlier full-history-v1 fold
table (its report and significance file were already committed), and the
observation exports with exclusion reasons for both data roots. All of it now
lives under `docs/results/`; the two exports exceed 10 MB uncompressed
(349.7 MB and 20.4 MB) and are committed gzipped, with the uncompressed hash
recorded. The import CSVs, the two observation stores, and the 1,321 snapshot
directories stay local: their SHA-256 hashes are in the manifest, and the raw
DoltHub exports are not redistributed pending the license check the report
already calls for.

**How the tracing was done.** `docs/results/build_manifest.py` hashes every
artifact (import CSVs, snapshot metadata and raw files, stores, run outputs,
exports, configs, the DoltHub clone heads) and writes `manifest.json` with 157
claims: each numeric statement in the report, its source file, the field or
derivation that produces it, and the value. Running the script with `--check`
recomputes everything from the committed artifacts (and the local-only sources
when present) and passed. Status counts: 73 read directly from a saved field,
77 derived by a stated computation from a saved file, 3 read from code
constants, 2 verified by a recorded run (`docs/results/verification-3.2.1.txt`
holds the pytest and ruff output: 181 passed, lint clean), 2 untraceable.

**Traced directly.** Import totals (292,018 quotes, 1,177 sessions, 260,296
training-eligible), every row of the exclusion table, the full-history and
SPY 2023 win rates, mean differentials, Diebold-Mariano and Newey-West
statistics and p-values, lag-1 autocorrelation, the block-10 and block-4
bootstrap intervals, the walk-forward specifications, and the rate, dividend,
and window parameters.

**Derived, not present in any output the study saved.** The bootstrap
intervals at block lengths 21, 63, and 126 were computed in an unsaved session;
re-deriving them from folds.csv with the package's own function (seed 0, 2,000
replications) reproduces every bound to the reported precision except the
block-63 lower bound, which renders as 5.04e-06, not 5.05e-06. They are saved
in `docs/results/full-history-v2/bootstrap-block-lengths.json`. The median and
interquartile per-fold improvement, the mean session RMSEs, and the per-year
table are computed from folds.csv (the per-year improvement is one minus the
ratio of mean RMSEs; the mean of per-fold improvements is negative in 2021 and
2023, so the "positive in every year" statement depends on that definition).
The refusal counts come from the import summary, which was printed and not
saved; they were recomputed from `full_chain.csv` with the XNYS calendar.

**Could not be traced, or disagrees with the saved outputs. Left unchanged.**

- "54 exchange holidays carrying stale rows": the export has 55 weekday
  holidays plus one Saturday (2020-01-04) outside 2019, so the refused dates
  are 47 + 55 + 1 = 103.
- "2 sessions where the SPY underlying close was missing" are real events,
  recorded in the metadata of the 2022-08-01 and 2022-09-19 snapshots, but
  those sessions were accepted with AAPL rows; they are not among the 103
  refused sessions.
- "SPY, QQQ, AAPL": the cloned `option_chain` table holds no QQQ rows, so the
  store, the folds, and every figure cover SPY and AAPL only.
- The report says the export files' hashes are recorded in every snapshot's
  metadata. Both imports ran before the 3.2.1 change that does this, so the
  snapshot metadata has no `source_files` entry; the hashes are in the
  manifest instead. Each snapshot's own raw_options.csv hash is in its
  metadata, and all 1,321 match.
- Block-63 lower bound 5.05e-06 (see above).

**Generated during the freeze.** The full-history exclusion export did not
exist; it was produced with `export --config config/eod-full.json
--include-excluded`, and the store's hash was identical before and after. The
SPY 2023 export existed; a fresh export was byte-identical to it. A "Data
coverage vs evaluation window" section was added to the report above
Limitations, with every figure read from the saved artifacts and listed in the
manifest: 1,280 raw dates of which 103 are non-sessions, 664 of 1,841 calendar
sessions absent from the source (roughly every other session through 2024),
236,516 evaluated quotes over 1,056 sessions, per-symbol counts, and the SPY
2023 subsample.

**Open questions for a v2 study.** A time-varying risk-free rate and an SVI
competitor (already listed in the report); whether the source ever carries QQQ
option rows; how the alternate-day gaps in 2020 to 2024 affect the serial
dependence adjustments, which are counted in stored sessions rather than
calendar days; and the source license before any export is redistributed.

## 2026-09-08 (later): correcting the flagged claims in RESULTS.md

Applied the corrections the freeze flagged, using manifest values verbatim
and recomputing nothing. The tag `study-v1` was left at b41237d, so the
manifest's `report_sha256` still describes the tagged report; the manifest
was not edited. `build_manifest.py --check` after the edits: all 157 claims
and all 13 committed artifact hashes pass, and the only reported problem is
that `docs/RESULTS.md` differs from the frozen report hash, which is exactly
this change.

- Symbols: "SPY, QQQ, AAPL" is now "SPY and AAPL" in the Summary and in the
  dividend-yield sentence (the configured 0.6% QQQ yield was never used); the
  Data section states that QQQ was requested and that the source
  `option_chain` table contains zero QQQ rows.
- Refusals: "54 exchange holidays" replaced by the manifest breakdown, 47
  weekend-stamped 2019 dates, 55 weekday exchange holidays, and 1 Saturday
  (2020-01-04), 103 refused dates in total carrying 22,282 rows.
- Missing SPY close: 2022-08-01 and 2022-09-19 are now described as sessions
  accepted with AAPL rows only, with the 284 SPY rows dropped, not as
  refusals.
- Block-63 lower bound: 5.05e-06 corrected to 5.04e-06.
- Provenance: the Data and Reproducibility sections now say the export file
  hashes are recorded in `docs/results/manifest.json`, not in snapshot
  `metadata.json`, because both imports predate the 3.2.1 hashing change; the
  claim that export queries are recorded was dropped, since nothing records
  them. The Reproducibility section names
  `docs/results/full-history-v2/bootstrap-block-lengths.json` as the saved
  source of the block-length table.

## 2026-09-08 (later): pre-registering the study v2 research plan

`docs/RESEARCH_PLAN.md` is committed before any code change for v3.3 onward.
The commit that adds it is its timestamp; later deviations go into its
section 10 and into this notebook, never into the text above them. The two
placeholders were filled from saved artifacts, not from memory:

- Constant risk-free rate: 4% (`rate: 0.04` in config/eod-full.json), recorded
  as `r` on every v1 observation in the committed export and in each
  snapshot's metadata.json.
- Baseline estimator: close-to-close realized volatility over the last 60
  returns of the underlying bar series, recorded as `baseline_source` =
  `dolt_prior_60_session_close_to_close` on every v1 observation and in each
  snapshot's metadata.json (`baseline_estimator: close_to_close` and
  `history_window: 60` in config/eod-full.json).

Every factual statement about v1 in sections 1, 2, 3, and 6 was checked
against docs/results/manifest.json, learning.py, and walkforward.py.
Consistent: 1,056 folds and the 10.4% median; positive improvement in every
calendar year (under the report's ratio-of-means definition; the mean of
per-fold improvements is negative in 2021 and 2023); the significance summary;
the dividend yields; the walk-forward settings (rolling window, 120-session
minimum, 250-session maximum, 1-session gap, per-fold reselection over alphas
0.01, 1, and 100 on the last two training sessions); 664 of 1,841 calendar
sessions absent; lag-1 autocorrelation 0.87; 249 of 250 shared training
sessions; the Harvey-Leybourne-Newbold correction; and the feature groups
(moneyness: log, squared, cubed; maturity: sqrt and log time; interactions of
moneyness and squared moneyness with sqrt time; carry: r*T and q*T; log
baseline volatility; put indicator; one indicator per symbol). Two mismatches
and one clarification, left unchanged because they touch the design:

1. Section 3 defines L as the session RMSE and d = L_base - L_model "as
   defined in walkforward.py". In walkforward.py the session loss behind the
   differential, both DM tests, the bootstrap, and the win rate is the mean
   squared spot-normalized pricing error (`baseline_loss`, `model_loss`); the
   RMSE columns are its square root and feed only the relative improvement.
   A differential in RMSE units is not the v1 differential, and the v1 lag-1
   autocorrelation of 0.87 belongs to the squared-loss series.
2. Section 6 keeps "Newey-West with 6 lags" for continuity with v1. The v1
   full-history run used 15 lags (floor(1.5 n^(1/3)) with n = 1,056); 6 lags
   was the SPY 2023 run with 83 folds.
3. Section 2 defines "prior session" as the previous session present in the
   store. The v1 baseline window is the last 60 close-to-close returns of the
   underlying bar series from the stocks database, which is nearly complete
   (2,075 bars per symbol from 2018-06-01 to 2026-09-04), so that definition
   does not describe the baseline's window.

## 2026-09-08 (later): research plan amendment 1

Section 10 of `docs/RESEARCH_PLAN.md` now carries Amendment 1, dated
2026-09-08, recording the definitional corrections found by the
fill-and-verify pass at fd50e25: the session loss is the mean squared
spot-normalized pricing error, with the relative improvement in RMSE terms;
Newey-West lags follow the v1 rule floor(1.5 n^(1/3)); the store-based "prior
session" definition applies to option-chain information only, not to the
realized-volatility window; and per-year breakdowns in Design C report both
the ratio-of-means and the per-fold median. No design, threshold, or decision
rule changed, no code for v3.3 has been written, and nothing above section 10
was edited.

## 2026-09-09: study v2, Stage 1, external inputs

Retrieved and committed the external inputs for Design A under
data/external/ with a full provenance record (data/external/PROVENANCE.md):
FRED DGS3MO (11,744 daily rows, 1981-09-01 to 2026-09-04), State Street's
family-wide ETF Historical Distributions workbook (34 SPY rows since 2018),
Apple's dividend history table (35 regular cash rows since 2018, saved as the
rendered DOM table with a browser-side hash match), and exports of the
DoltHub stocks `dividend` and `split` tables used for AAPL ex-dates and as a
cross-check. scripts/build_external_inputs.py parses the raw files into
dividends.csv (69 rows) and splits.csv (AAPL 4:1 on 2020-08-31).

Findings that shape Stage 2: Apple's amounts are not split-adjusted and the
stocks store's AAPL closes are not split-adjusted either, so no static
rescaling is right on both sides of the split; the series module will rebase
pre-split dividends by 1/4 whenever the price they divide is post-split and
never touch stored prices. Apple publishes record dates only, so AAPL
ex-dates come from the DoltHub dividend table matched to the record dates;
the naive settlement rule would have been a day off on three Veterans Day
record dates. Retrieval quirks: FRED answered only curl's default User-Agent;
Apple's page needed a real browser. Confirmed at CHECKPOINT 1.

## 2026-09-09: study v2, Stage 2, engine changes (3.3.0)

Implemented the v3.3 items of plan section 9: dated rate and dividend inputs
(`options_engine/carry_inputs.py`), constant and series config forms with the
v1 flat fields still valid, frozen observation sets (`observation-set build`,
`walk-forward --observation-set`), effective r and q on every export row and
fold, and the Amendment 1 fold columns (baseline_mse, model_mse, rho, d).
Constant v1 carry reproduces every stored implied-volatility target exactly,
so C0 is the v1 pipeline on the same rows. 202 tests pass, lint is clean.

Interpretations the plan does not spell out, recorded here before any run:

- Under configuration k the learning target is the implied volatility of the
  session mid inverted under r_k and q_k, so target, features, and pricing
  share one carry. Rows whose target does not identify under some
  configuration (in practice in-the-money puts near the r = 0 bound, mostly
  2020-2021) are drop reasons and leave set A for every configuration.
- Dividend history coverage is declared (2018-01-01 to the 2026-09-09
  retrieval) and windows outside it are refused; a rate quote or bar older
  than 10 days is refused. None of these rules fires on a stored session.
- config/v2 files sit one directory deeper, so data_root differs textually
  from config/eod-full.json while resolving to the same store.

Review: seven independent reviewers (rate, dividend, information flow,
observation set, configuration, tests, plan conformance) read the uncommitted
change; the adversarial verification fan-out hit a session limit, so each
finding was verified by hand instead. Fixed: the set is now enforced on reuse
(full match, zero further drops, config among the builders), its hash is
verified on read including .csv.gz, constant-mode blocks reject stray keys,
both dividend forms at once are refused, failed rows carry no partial carry
values, the collector and the train, ingest, and score-snapshot commands
refuse series configs, the report survives a degenerate statistic, and the
tests that had been validating 0 == 0 now run a model that learns. Not
changed, for decision at CHECKPOINT 2: the v1 support guard reverts the model
to the baseline on sessions whose rate lies outside the training window's
range, which never happens under constant carry and happens on 21 of 1,056
sessions under the historical rate (17 in the 2022 hikes, 4 in late 2025),
biasing S_1 and S_3 toward zero; the plan's "nothing else changes" keeps the
guard, so the choice needs an amendment either way. Also for that checkpoint:
the plan writes the conversion as ln(1 + y) where the file quotes percent;
the code applies ln(1 + y/100) as the Stage 2 specification says.

## 2026-09-09: study v2, Stage 3, observation set A and the C0 control

Built docs/results/v2/observation-set-A.csv (committed gzipped; uncompressed
SHA-256 0f6c47bf691a90a2ceb60e6b5fdf447fed4d04cb8fa3334a121316dc8448f57c) from
the four Design A configurations: 253,554 of the 260,296 v1-eligible rows
kept, 6,742 dropped (2.6%), every one because the implied-volatility target
does not identify under a historical-carry configuration (C1 5,964, C2 504,
C3 6,279, C0 none); no rate, dividend, or bar input was ever unavailable. The
drops are 5,243 puts and 1,499 calls, 4,900 SPY and 1,842 AAPL, 62% in
2020-2021, 74% within 30 days of expiry: in-the-money puts whose mid sits
below the r = 0 lower bound. No session is lost, so the 1,056 fold boundaries
are the v1 ones. Inside the evaluation window the set holds 230,927 quotes
against v1's 236,516.

C0 on set A (docs/results/v2/design-a/C0, 6 min 46 s): median rho 0.1086
(v1 0.1045), mean d 4.73e-04 (v1 4.50e-04), win rate 0.664 (identical to v1,
701 of 1,056), DM 3.672 (v1 3.671), Newey-West 1.224 (v1 1.228), mean learned
coverage 0.99702 with the same 7 partial-coverage folds as v1. Folds whose
evaluation rows are untouched still differ from v1 because the intersection
also removes training rows. C0 reproduces v1 up to the intersection, as
section 3 requires, and CHECKPOINT 2 was reported with the open decisions
from Stage 2 (support guard, target re-solve, conversion wording, coverage
rules, config data_root).

## 2026-09-13: study v2, Stage 4, Design A runs and comparison

Amendment 3 was recorded first; the support guard change (3.3.1) was then
verified as a no-op for the control by rerunning C0 on the amended code: all
three output files are byte-identical to the committed Stage 3 run. C1, C2,
and C3 ran on observation set A with the v1 walk-forward settings (rolling,
120 minimum, 250 maximum, gap 1, per-fold alpha reselection), about 10.5
minutes each in parallel; every run matched the set fully, dropped nothing,
and has no zero-coverage fold (the same 7 partial-coverage folds as v1).

| Run | Median rho | Mean d | Win rate | S_k [95% interval, block 21] |
|---|---:|---:|---:|---:|
| C0 | 0.1086 | 4.732e-04 | 0.664 | 1 (control) |
| C1 | 0.1036 | 4.742e-04 | 0.637 | 0.955 [0.665, 1.230] |
| C2 | 0.1060 | 4.732e-04 | 0.665 | 0.977 [0.891, 1.121] |
| C3 | 0.1070 | 4.748e-04 | 0.646 | 0.986 [0.762, 1.281] |

`compare-configs` (paired circular block bootstrap, block 21, 10,000
replicates, seed 20260908; sensitivity at blocks 10, 63, 126 agrees) gives the
section 3 label **structure dominant**: S_3 = 0.986 with the
lower bound 0.762 above 0.5. The mean of d_3 is
4.748e-04 with interval [6.32e-06,
1.40e-03], so the v1 improvement survives full
carry correction. The carry-only check, median(L_base,3) - median(L_model,0)
= 2.136e-06 with interval [2.58e-07, 3.86e-06],
says correcting carry in the baseline alone does not close the gap: the
baseline priced under historical carry still loses to the model priced under
the constant v1 carry. Two things to carry into the writeup rather than the
decision: the historical rate lowers the win rate (0.664 to 0.637 in C1,
0.646 in C3) while leaving the median rho and mean d essentially unchanged,
and the S_1 interval is the widest of the three.

Deviations from the plan text, all recorded in Amendment 3 before these runs:
the target re-solve and its 2.6% intersection drop, the rate conversion in
percent, the declared history and staleness guards (inert), the config/v2
data_root, and the support guard. The manifest was rebuilt to cover the
study v2 inputs and artifacts; its report hash now describes the corrected
docs/RESULTS.md at ee8ce3c rather than the study-v1 tag. docs/TALK_OUTLINE.md
still carries its fill slots; a guard-sensitivity run (C1 and C3 with the v1
guard kept) has not been made.

## 2026-09-13: study v2, Design B, Stage 1 (baselines and set B)

Amendment 4 was recorded first. Implemented `options_engine.baselines` (3.4
series): B1 takes the same contract's implied volatility at the prior
available session, which under Amendment 4 is exactly the target apply_carry
solves on the t-1 row (S_{t-1}, time to expiry from t-1, r_{t-1}, q_{t-1});
absent contracts are interpolated linearly in strike within the same expiry
and option type at t-1, never beyond the quoted range. B2 fits raw SVI total
variance per t-1 expiry slice to the out-of-the-money mids by vega-weighted
least squares, keeps the standard bounds and the butterfly check, and is
evaluated at t's strikes against t's forward; failures fall back to B1.

Set B: 154,110 of set A's 253,554 rows (60.8%), 1,126 of 1,177 sessions,
144,072 evaluated rows in 1,015 sessions from 2020-10-23. The drop is a
property of the source: each date's chain carries three (sometimes four)
expirations at fixed offsets of about 14, 28, and 65 days, so the two short
ones roll with the date and only the monthly expiry exists at the prior
session; 88,753 of the 99,444 drops are `expiry_absent_at_prior_session`,
10,504 `strike_outside_prior_range`, and the rest are first sessions, single
strikes, or a missing type. 51 sessions lose every row, mostly the sessions
just after a monthly roll. Kept rows: 57.4% same contract, 42.6%
interpolated; median gap to the prior session 2 days, maximum 14. Median
|B1 - RV| is 0.0765 (median B1 0.281 against RV 0.212).

SVI: a first pass fell back on 49.7% of slices, which a diagnosis traced to
the optimizer, not the data: the raw-parameter least squares surface is flat
along a degenerate direction (b toward 2, |rho| toward 1, negative a) that
fits the quoted range but fails the bounds, and a quarter of fits hit the
evaluation cap. Refitting in (w_min, b, rho, m, sigma) with the minimum total
variance as a box bound, a penalty for Lee's wing bound, an analytic Jacobian
and data-driven starts (commit 4e5ffa4) gives 3.9% slice fallbacks (117 too
few strikes, 56 butterfly, 3 no convergence, 1 bounds), 2.6% of rows, so B2
is not fallback-contaminated under Amendment 4. Median |B2 - B1| on fitted
rows is 0.0105. B1 is byte-identical between the two passes.

Reported at the CHECKPOINT with one open point for the writeup: the plan's
exclusion rule makes set B lean toward monthly expiries (median 39 days to
expiry against 28 for the dropped rows), so Design B answers its question on
a longer-dated subset than Design A.

## 2026-09-14: study v2, Design B, Stage 2 (runs on set B)

Five walk-forwards on set B with the v1 settings (rolling 250, minimum 120,
gap 1, per-fold alpha reselection) under config/v2/C3.json: B1 alone and B2
alone in baseline-only mode, and M(RV), M(B1), M(B2) with the base volatility
swapped through `--baseline-file`. All five matched the set fully, dropped
nothing, and evaluate the same 1005 sessions from 2020-11-16 to
2026-09-04 (set B's first sessions supply the 120-session training window,
so the window opens ten sessions later than Design A's). About 8.5 minutes in
parallel; no zero-coverage fold in the learned runs. A first launch failed at
argument parsing (an unsplit shell variable) and was rerun identically.

Set B control (Amendment 4): M(RV) on set B has median rho 0.1623, mean d
2.530e-04, win rate 0.708 against C3 on set A's 0.1070,
4.748e-04, 0.646; the RV baseline's median session MSE is 1.609e-05 on
set B against 1.399e-05 on set A. Restricting to the longer-dated set B
therefore flatters the learned model relative to its flat baseline, so every
Design B number is read on set B only and not against Design A.

## 2026-09-14: study v2, Design B, Stage 3 (comparison)

`compare-baselines` (paired circular block bootstrap, block 21, 10,000
replicates, seed 20260908; sensitivity at 10, 63, 126):

| Comparison | Mean L_baseline - L_model | 95% interval | Median relative improvement | Win rate | Label |
|---|---:|---:|---:|---:|---|
| M(RV) vs B1 | -1.692e-05 | [-2.41e-05, -1.14e-05] | -1.8900 | 0.054 | baseline wins |
| M(RV) vs B2 | -1.316e-05 | [-2.04e-05, -7.64e-06] | -0.4545 | 0.154 | baseline wins |
| M(B1) vs B1 | 4.104e-07 | [5.39e-08, 8.40e-07] | -0.0119 | 0.463 | adds value |
| M(B2) vs B2 | -4.825e-06 | [-8.20e-06, -2.50e-06] | -0.2382 | 0.241 | baseline wins |

The primary claim does not hold: the prior-session implied volatility beats
the v1 model at every block length, the model's session RMSE is about 2.9
times B1's at the median, and it wins 5.4% of sessions. Per section 8
the value claim is downgraded: the v1 model captured structure that a flat
baseline lacks, but no more than persistence of the previous smile provides.
M(B1) versus B1, the relevant test of incremental value, carries the
mechanical label "adds value" because its block-21 interval lies above zero,
but the median relative improvement is negative, the model loses most
sessions, and the block-63 and block-126 intervals include zero; the report
prints these caveats, and I read the incremental value beyond persistence as
not robust. B2, the SVI smile, also beats M(RV), and refitting relative to it
(M(B2)) is worse than B2 alone. B2 is not fallback-contaminated (3.9% of
slices), so its secondary labels stand.

Implementation choices not spelled out by the plan, all recorded before the
runs: interpolation within the same expiry and option type; SVI slices fitted
to out-of-the-money quotes (puts below the forward, calls at or above it)
with vega taken from the t-1 inversion; the fitted smile persisted as implied
volatility, so B2 at t is sqrt(w(k_t)/T_(t-1)) with k_t against t's forward;
the first-pass fitter replaced (commit 4e5ffa4) before any run because half
its fallbacks were optimizer artifacts. The manifest was rebuilt to cover set
B, the baselines, the five runs, and the comparison. docs/TALK_OUTLINE.md's
Design B slot can be filled from docs/results/v2/design-b/comparison.json.

