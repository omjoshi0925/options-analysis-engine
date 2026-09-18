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

## 2026-09-14: study v2, Design B, stale-quote diagnostic (Amendment 5, exploratory)

Specified after the Design B result and recorded as Amendment 5 before any
code. Over set B, 88,408 of 154,110 observations have the same contract
quoted at the prior available session (the rest have an interpolated B1);
892 of those (1.0%, 0.6% of set B) carry a mid identical
to the prior session's. Where the contract is quoted at both sessions, the
relative mid change has median 0.096 and p90 0.394; it is
smaller for SPY (median 0.041) than AAPL (0.113), grows with the gap to the
prior session (0.072 at one day, 0.191 at five or more), and is largest
nearest the money. The prior-quote universe is set A, the universe B1 was
built from; 14 interpolated rows had a prior quote outside it and are not
counted as comparable.

Sensitivity (same training windows and models, only the evaluation rows
restricted; paired block bootstrap, block 21, 10,000 replicates, seed
20260908), against the pre-registered full-set-B figures:

| Comparison | Mean L_baseline - L_model | 95% interval | Median relative improvement | Win rate | Label |
|---|---:|---:|---:|---:|---|
| M(RV) vs B1, full set B | -1.692e-05 | [-2.41e-05, -1.14e-05] | -1.8900 | 0.054 | baseline wins |
| M(RV) vs B1, changed-mid | -1.895e-05 | [-3.00e-05, -1.11e-05] | -1.5780 | 0.078 | baseline wins |
| M(B1) vs B1, full set B | 4.104e-07 | [5.39e-08, 8.40e-07] | -0.0119 | 0.463 | adds value |
| M(B1) vs B1, changed-mid | 5.250e-07 | [7.88e-08, 1.04e-06] | -0.0013 | 0.497 | adds value |

Neither label changes. B1's median session RMSE is 2.77e-04 on the
unchanged-mid rows (379 sessions hold any) against 1.26e-03 on the
changed-mid rows: the mechanical advantage of an unchanged quote is real,
about a fourth of the usual error, but it touches 0.6% of set B and B1 wins by
the same margin without it. M(B1) versus B1 stays fragile on the changed-mid
subset (median relative improvement -0.001, win rate 0.497, blocks 63 and 126
include zero). Eight sensitivity runs took about 24 minutes in parallel; the
unchanged-mid runs skip the 626 sessions with no unchanged row. Outputs:
docs/results/v2/design-b/stale-quote-diagnostic.json, the sensitivity/ tree,
and a section of the Design B report; the pre-registered numbers are
unchanged. Version 3.4.1.

## 2026-09-14: study v2, Design C, Stages 0 to 2 (exploratory)

Everything in this phase is exploratory (plan section 5, Amendment 5) and
labeled so in every output. Stage 0: FRED VIXCLS retrieved 2026-09-14
20:52:03 UTC with curl's default User-Agent (9,574 rows, 302 blank; sha256
60f2ec1e...), recorded in data/external/PROVENANCE.md section 7. The regime
for session t is the most recent VIXCLS observation dated strictly before t;
terciles over the 1,056 set A evaluation sessions cut at 16.45 and 20.16
(352 sessions each; 344, 335, and 326 on set B). Moneyness terciles of
|log(K/F)| over the 230,927 set A evaluation rows cut at 0.0557 and 0.1350
and are reused on set B; both cut points are recorded in breakdowns.json.

Stage 1: `walk-forward --exclude-features` refits the learner without one
feature group (moneyness; maturity interactions; the symbol indicator, which
with two symbols is one SPY/AAPL contrast, not a group) on the same folds
under C3, for M(RV) on set A and M(B1) on set B. The full models were rerun
with `--save-predictions` and reproduce the pre-registered C3, M(RV), and
M(B1) fold tables byte for byte. Two launches failed before the runs
counted: unsplit zsh variables (argparse saw one token), and the saved
predictions creating the report directory ahead of the report, fixed in
08095d7 with a test; the three full runs were relaunched after the fix.

M(RV) on set A, paired block bootstrap (block 21, 10,000 replicates, seed
20260908) for the change against the full model:

| Model | Delta (median rho) | Mean d | Win rate | Change in mean d [95%] | Change in Delta [95%] |
|---|---:|---:|---:|---:|---:|
| full | 0.1070 | 4.748e-04 | 0.646 | | |
| without moneyness | -0.1161 | 4.643e-04 | 0.390 | -1.054e-05 [-1.37e-05, -7.88e-06] | -0.2232 [-0.2616, -0.1835] |
| without maturity interactions | 0.0456 | 4.706e-04 | 0.545 | -4.200e-06 [-6.62e-06, -2.38e-06] | -0.0614 [-0.1034, -0.0332] |
| without symbol | 0.0775 | 4.724e-04 | 0.626 | -2.426e-06 [-4.46e-06, -9.19e-07] | -0.0296 [-0.0529, -0.0064] |

Every ablation hurts; moneyness carries the result. M(B1) on set B: every
ablation also hurts, by -4.8e-08 to -1.3e-07 in mean d with intervals below
zero, while Delta stays near -0.01, consistent with that model adding almost
nothing to B1.

Stage 2 breakdowns (d and rho by symbol, maturity bucket, moneyness tercile,
VIX tercile, and gap to the prior available session; an interval only with
30 or more sessions). M(RV) vs RV on set A: 31 to 90 days median rho +0.189
(win 0.760) against -0.009 (win 0.493) at 30 days or fewer; middle moneyness
tercile +0.374 (win 0.909) against -0.021 in the low tercile; high-VIX
+0.191 against low-VIX +0.038; AAPL +0.141 against SPY +0.074. M(RV) vs B1
on set B: every cell strongly negative (median rho -1.1 to -3.3, win rates
at or below 0.09). M(B1) vs B1: mean d slightly positive in most cells with
median rho near zero or negative (SPY -0.067, low moneyness -0.053).
Sparsest cells: the more-than-90-day bucket is empty in every entry; gap "4"
on set A has 16 sessions (3,951 observations, no interval) and "5+" 40; on
set B gap "4" has 45 and "5+" 41. CHECKPOINT reported with the VIX cut
points, the M(RV) ablation table, and these counts.

## 2026-09-15: study v2, Design C, Stage 3 and Amendment 6 (exploratory)

CHECKPOINT confirmed with two additions. The empty more-than-90-day bucket
is a property of the source, not of the sets: the imported DoltHub chains
list two to four expirations per symbol and session and none beyond 67
calendar days. Measured over the whole sets and over their evaluated rows
alike, the maximum time to expiry is 66.958 days (T = 0.18345) in set A and
65.042 days (T = 0.17820) in set B, the minimum 10.000 days in both; the odd
hour is the daylight-saving offset between the session close and the
expiration close. The instruction that accompanied the confirmation put the
ceiling at roughly 45 days; the data do not (81,482 of set A's 253,554 rows
expire more than 45 calendar days out), so Amendment 6 records the measured
values. Amendment 6 is exploratory in scope, changes no estimand or rule,
and states that the study covers short-dated options only and supports no
term-structure claim.

Stage 3: `design-c breakdowns` now records each entry's observed maturity
range and empty buckets, and `design-c ablations` records the median
differential and the share of the summed differential carried by the ten
largest sessions (77.5% of 1,056 for M(RV) on set A; 90.5% of 1,005 for
M(B1) on set B). Both files were regenerated; every previously recorded
number is unchanged and the new fields are additions. The report reads the
ablations in words: removing the moneyness features moves Delta from +0.107
to -0.116 while the mean differential moves from 4.75e-04 to 4.64e-04,
because a few high-error sessions dominate the mean (without the ten
largest, the set A mean d is 1.08e-04). The same two points went into
RESULTS.md's limitations and section 6 of the talk outline. Version 3.5.0;
manifest rebuilt with the design_c block (nine runs, saved predictions with
uncompressed hashes, the three files, and the headline); `--check` passes.

## 2026-09-15: study v2 locked (Design D, section 7, Amendment 7)

Locked at tag study-v2-locked (commit 331946a); the code commit is f3e85ec,
`options_engine` 3.6.0. Amendment 7 (a2f2b46) records the pre-registered
expectations for the fresh evaluation, derived from Designs B and C and fixed
before any fresh session is scored: B1 beats M(RV) on the primary loss with
M(RV)'s win rate under 0.15; M(B1) versus B1 is null at every block length,
and confirming that null is the result; M(RV) versus the RV baseline stays
positive in median rho, concentrated in high-VIX sessions (strictly-prior
VIXCLS above the Design C cut point 20.16) and at maturities of 31 days or
longer.

The locked commands (4b6b9db): `predict-locked --session t` forms the prediction
set from the store's eligible C3 rows at the prior available session that
outlive t's close and prices each under the RV baseline, B1, M(RV), and M(B1)
with S_t, r_t, q_t and prior-session information only; it refuses if the
chain for t is in the store, if the store holds a later session, if t is not
after the lock date, if the files exist, or if any locked file's hash differs
from docs/lock.json. `score-locked --session t` refuses unless the prediction
file is committed and unchanged and the chain was imported after that commit;
it matches on (symbol, contractSymbol), ignores contracts absent from the
prediction set, and appends one line to docs/FRESH_EVAL.md.
`fresh-eval-report` refuses until the sample rule is met (60 available
sessions after the lock or all sessions available by 2027-03-31). Four tests
cover the lock verification, the refusals, the committed-file gate, the
import-order check, and the sample-rule gate; 232 tests pass.

A smoke run of the real path (session 2026-09-08 against the store's
2026-09-04, with a synthetic S_t appended to a scratch copy of the bars,
output discarded, nothing committed) predicted 281 contracts (163 SPY, 118
AAPL) in 13 seconds: M(RV) trained on 250 sessions (2025-09-03 to
2026-09-03, alpha 0.01), M(B1) on 249 (alpha 100; 26,721 same-contract and
23,377 interpolated training rows), every contract inside the support guard.
Two interpretations of section 7 are recorded in docs/LOCK.md: the training
universe for fresh sessions is the store's eligible rows that price under C3
(within 463 rows of set A over the study span), and the scoring universe is
every predicted contract present at t rather than the 500-per-symbol
evaluation sample. The plan's step 2 prices under the locked model, B1, and
the RV baseline; the prediction file adds M(B1) so expectation 2 can be read
from the same sample, and the log carries four losses rather than three.
docs/LOCK.md records the locked commit, the hashes of the configuration and
14 modules, the invocations, the sample rule, and the per-session protocol;
docs/lock.json is what the commands verify; the manifest covers both.
Nothing is scored until a session after 2026-09-15 is available in the
source, and the rate, bar, and distribution files must be refreshed before
the first prediction (the committed bars end 2026-09-04).

## 2026-09-15: repository size review and hygiene pass

Read-only inventory first. The .git directory is 207 MB on disk (756 loose
objects; GitHub reports 196 MB packed) and the working tree 16.5 GB, the
latter almost entirely ignored material: the two DoltHub clones (13.4 GB),
the observation store and its snapshots (1.85 GB), the venv, and the
uncompressed exports under results/. Tracked content is 208 MB in 261 files,
of which 204 MB in 152 files is referenced by docs/results/manifest.json or
docs/LOCK.md: the 101.5 MB v1 exclusion export (the source of the RESULTS.md
coverage claims), the three Design C prediction files (48.5 MB), the
observation sets, baselines-B, the stale-quote subsets, the SPY 2023 export,
and the fold tables. The ten largest blobs were each added once at one path
and are all in HEAD; the history-only material (seven superseded manifests,
one workbook, one bar file) is 4.9 MB packed. The only large tracked
material not referenced anywhere was examples/validation/ (2.97 MB of
synthetic demonstration plots and a demo CSV).

Decision at the checkpoint: no history rewrite and no tag change. A rewrite
that purged the v1 export would rewrite 60 of the 95 commits, move both
tags, and falsify the hashes cited in docs/LOCK.md, docs/lock.json,
docs/NOTEBOOK.md, Amendments 1 and 3, CITATION.cff, and docs/REPRODUCE.md;
even the narrowest purge (the Design C predictions) moves study-v2-locked and
the locked code commit named in LOCK.md. The remote has no forks but
recorded 200 clones from 53 addresses in the prior 14 days, of which CI runs
explain at most 46, so copies of the current history exist elsewhere.

Hygiene done instead: examples/validation/ removed from HEAD (nothing in the
manifest or LOCK.md points at it; the README sentence now says the outputs
are regenerated by `demo`), .ruff_cache added to .gitignore, a "Repository
size" section in docs/REPRODUCE.md, and the release-asset rule for
artifacts above 10 MB in CONTRIBUTING.md. Measured for that section: a
depth-1 clone of study-v1 from GitHub with --no-tags downloads 105 MiB
packed and passes build_manifest.py --check at the tag (157 claims, 17
skipped as local-only, 13 committed artifacts); without --no-tags git also
fetches the study-v2-locked tree and the clone is about 200 MB. `git gc
--aggressive --prune=now` was run for local packing only. Both tags point
where they did: study-v1 at b41237d, study-v2-locked at 331946a.

## 2026-09-17: early-exercise diagnostic (Amendment 8, exploratory) and reviewer extract

An outside review flagged that the engine prices American-style contracts
with the European closed form. Amendment 8 records the diagnostic before it
ran; everything in it is exploratory, no reported number is replaced, and no
locked module is touched (the new module options_engine.early_exercise and
the `early-exercise-diagnostic` command are outside the lock).

Trace, with file and line at the locked commit: the RV baseline, M(RV), B1,
B2, M(B1), and M(B2) are all priced by learning.py:110-112
price_with_volatility, the European BlackScholesEngine.price (core.py:62),
through evaluate (learning.py:123-128) at walkforward.py:108-109; B1's sigma
is the t-1 row's iv_brent_volatility from carry_inputs.py:323, a European
inversion (iv.py:53-54 objective), or its strike interpolation
(baselines.py:88); B2 fits SVI to those European implied volatilities
(baselines.py:187-217, 244); the learning target is the same European
inversion (learning.py:71); the locked predict path prices with
price_with_volatility at locked.py:229 and identifies with implied_volatility
at locked.py:395. The binomial tree (american.py:83-91) enters no study loss:
it is called only by analysis.py:66 at import time and by the cli price
command.

Diagnostic (docs/results/v2/early-exercise-diagnostic.json), streamed from
the saved prediction files in 20,000-row chunks: premiums are American minus
European price on the same 200-step CRR tree, vectorized over rows, at each
quote's own European implied volatility (the bisection matches iv.py to
2e-12 on real rows; doubling the steps moves the fraction by at most 0.05
points on 2,000 rows). Set A, 230,927 rows: mean 0.40% of the mid, median
0.06%, p90 1.24%, p99 2.73%, maximum 8.8%; 31.9% of observations exceed the
quote's tick (0.05 for AAPL at or above $3, 0.01 otherwise, inferred from the
quotes). Puts 0.70% and 52.7% above the tick, calls 0.03% and 6.0%; 2022
onward 0.45% and 34.8%, the near-zero years 2020-21 0.07% and 13.7%; 31 to 90
days 0.53%, 30 days or fewer 0.29%; SPY 0.45%, AAPL 0.35%; moneyness terciles
0.49% (low), 0.41%, 0.29% (high). Set B, 142,942 rows: mean 0.45%, 33.0%
above the tick, puts 0.79% and 57.2%. At each method's own sigma the means
are close to the quote-implied figure (set A: M(RV) 0.47%, RV 0.52%).

Cancellation test on the 83,438 same-contract set B rows (78,414 usable in
1,004 sessions; 107 sit on the tree's intrinsic value and imply no
volatility; the European re-inversion reproduces the stored B1 sigma to
1.4e-12): moving B1 to the consistent treatment (invert on the tree at t-1,
reprice on the tree at t) lowers its session MSE from 6.39e-06 to 6.17e-06,
and repricing M(RV) on the tree lowers its MSE from 2.46e-05 to 2.40e-05. The
mean of L_B1 - L_M(RV) moves from -1.82e-05 to -1.78e-05, a change of
+3.8e-07 with interval [6.2e-08, 6.7e-07]: the European engine does favor B1,
by 2.1% of the gap. M(B1) repriced on the tree at its European-derived sigma
gets worse (5.87e-06 to 6.40e-06), so the M(B1) versus B1 differential flips
from +5.1e-07 to -2.3e-07 on these rows; that treatment is inconsistent (the
model learned against European B1 sigmas) and is reported as such.

Sensitivity, same folds and bootstrap, restricted to the 95,808 set B rows
whose premium is at or below the tick (every session keeps a row): M(RV)
versus B1 stays "baseline wins" (mean -1.55e-05, interval [-2.27e-05,
-1.02e-05], median rho -1.99, win 0.061; pre-registered -1.69e-05 [-2.41e-05,
-1.14e-05]). M(B1) versus B1 moves from "adds value" (+4.10e-07 [5.4e-08,
8.4e-07]) to "no evidence either way" (+1.98e-07 [-1.20e-07, +5.53e-07], win
0.447; every block length includes zero). One label changes, the one the
Design B report already called fragile; the pre-registered numbers stand.
The full-row losses recomputed from the prediction files reproduce the
pre-registered means and intervals exactly, which validates the streaming
computation. Timing 374 s in total; peak resident memory 741 MB
(a first run kept per-row label strings for every sigma variant and peaked at
910 MB; the aggregates were switched to shared integer codes and the numbers
were verified unchanged).

Reviewer extract (docs/results/v2/extract/): 38,545 evaluated observations
from set A (22,237 also in set B), a deterministic stratified sample (seed
20260908) capped at 700 rows per symbol x year x option type x maturity
stratum (56 strata; the 2020 strata are exhausted), 15.3 MB uncompressed,
with the RV, M(RV), B1, and M(B1) sigmas and prices, the quote's European
implied volatility, the tree premium, and the tick; plus verbatim copies of
all 29 fold tables and a README stating that no reported number comes from
the sample. RESULTS.md gained the Design B forward pointer after the v1
headline and two limitations (European pricing with the measured premium
distribution; intervals conditional on the fitted models), the talk outline
its section 6 line, and the manifest covers the diagnostic and the extract.
Version 3.6.1; study-v1 and study-v2-locked unmoved.

## 2026-09-17: fresh evaluation, first session (2026-09-16)

Inputs refreshed in one pass at 18:36 UTC (data/external/PROVENANCE.md
section 9): DGS3MO through 2026-09-15, bars through 2026-09-16 (six new
rows, every earlier row byte-identical), everything else re-retrieved and
byte-identical; `--dividend-history-end 2026-09-17`. The options source,
pulled to its 2026-09-16 update, holds one session after the lock date,
2026-09-16 (AAPL 194 rows, SPY 210). No chain for it was in the store. The
pre-lock sessions 2026-09-08 to 2026-09-15 were left out of the store,
because no chain is imported before its session's prediction file is
committed, so the prior available session for 2026-09-16 is 2026-09-04, a
12-day gap.

Protocol as run, all UTC: predict-locked 18:41:13 to 18:41:25 (281 contracts,
163 SPY and 118 AAPL, 219 inside the models' support; M(RV) trained on the
250 sessions 2025-09-03 to 2026-09-03 with alpha 0.01, M(B1) on 249 with
alpha 100; r 4.03%, q 0.32% for AAPL and 0.99% for SPY, RV 32.4% and
11.5%); prediction commit 4c1b8fa at 18:41:26; chain export 18:41:50 (404
rows); import 18:41:51 (317 rows stored, 287 eligible); score-locked
18:41:53; scores commit d4e2986. Of the 281 predicted contracts, 49 were
quoted at 2026-09-16, 2 of those below the training floor, and 47 were
scored (23 AAPL, 24 SPY); 232 were absent, the 2026-09-04 expiries having
rolled off the source's short list within 12 days; 268 contracts quoted at
2026-09-16 were not in the prediction set and were ignored. Spot and time to
expiry agree exactly between the prediction file and the store.

Session losses, the mean squared spot-normalized error over the 47 scored
contracts: RV 3.03e-05, B1 1.65e-05, M(RV) 5.82e-06, M(B1) 1.11e-05. M(RV)
beat B1 on this session (rho 0.41) and M(B1) beat B1 (rho 0.18). One session
whose B1 is twelve days old says nothing; no inference before the sample
rule is met (1 of 60). No refusal fired. The manifest gained a
fresh_evaluation block listing the per-session prediction and score files
(docs/FRESH_EVAL.md is listed without a hash because it grows). study-v1 and
study-v2-locked unmoved.

## 2026-09-17: Amendment 9, the pre-lock sessions imported, and the one-command fresh session

Amendment 9, decided after the 2026-09-16 result was seen and recorded as
such: sessions dated on or before the lock date may be imported at any time
as prior-session information, because they are ineligible for Design D
scoring; the predict-before-import rule applies to scorable sessions only.
The 2026-09-16 session stands as scored with its 12-day-gap B1 noted in
docs/FRESH_EVAL.md, and the change favors B1, the competitor, not the locked
model, since later sessions inherit a prior session one day old.

The source sessions 2026-09-08 to 2026-09-15 (2,264 chain rows; the rows
stamped on Labor Day were excluded) were imported at 19:21 UTC from the
already-committed bars: six sessions, 1,919 rows stored, 1,728 eligible; no
prediction and no scoring for them. predict-locked afterwards still refuses
2026-09-16 (chain already in the store), 2026-09-15 (not after the lock
date), and 2026-09-17 (no underlying close yet), writing no file. The
2026-09-16 chain export was removed from the repository root (its hash is
in the snapshot metadata) and per-session exports are now ignored under
data/chains/.

scripts/fresh_session.sh runs one fresh session end to end: it pulls the
option source, looks for an unscored session after the lock date, and exits
quietly with none; otherwise it refreshes the rate, bars, and distribution
inputs (the DoltHub dividend table is the cross-check for the issuer files
that need a browser; a later ex-date there stops the run), appends a row to
the automated refresh log in PROVENANCE.md section 10, runs predict-locked,
commits the prediction files, and only then exports that session's chain,
imports it, scores it, rewrites the status line, rebuilds the manifest, and
pushes. It refuses a dirty tree or a local main that differs from origin,
and any refusal from the locked commands stops it. Tested on the real state:
--dry-run reports that no session after 2026-09-15 is unscored; the real run
exits 0 with no output, no commit, and a clean tree. It is meant to run each
weekday morning (docs/REPRODUCE.md). The manifest was rebuilt after the
history import (the store hash changed); study-v1 and study-v2-locked
unmoved.

## 2026-09-17: PAPER.md draft added and verified against the artifacts

docs/PAPER.md is the author's draft (dated 2026-09-17), copied in and checked
claim by claim against docs/results/manifest.json and the committed JSON and
CSV outputs. Filled: the first and last evaluated session, 2020-10-23 and
2026-09-04, from design-a/C0/folds.csv (identical to the v1 fold dates). Not
filled: the v1-guard sensitivity sentence, because no such run exists (the
2026-09-13 entry above records that C1 and C3 with the v1 guard kept were
never run, and design-a/comparison.json has no guard block); the slot carries
a bracketed note, and section 3's parenthetical that the v1 guard "is
reported as a sensitivity" is left for the author, since correcting it
changes what the paper claims.

Plain factual corrections made: the learning target is log(IV / sigma_RV)
(learning.py:71), not log implied volatility; the support guard reverts an
observation, not a session, on maturity, baseline volatility, or
log-moneyness; set B spans 1,126 sessions with 1,005 evaluated; M(B1) versus
B1 clears zero at blocks 10 and 21, not at 21 only; the ten sessions that
carry 77.5% of the summed differential are among 1,056 set A sessions, not
1,005; the short-maturity cell is 30 days or fewer; the tree-inversion
comparison is on the 78,414 same-contract rows; the manifest holds 157
claims for the v1 report plus hashed v2 blocks, not a grown claim count; the
shallow clone is about 110 MB with --no-tags, not 130 MB. Reported without
rewriting: the section 1 sentence that every amendment's commit precedes the
runs it governs (Amendments 5, 6, 8, and 9 were specified after the results
they concern); the loss equation writes one spot per session where the code
divides by each row's own underlying; "the put by parity" holds only when
the call is the out-of-the-money side (core.py prices that side directly);
the SVI fit also carries Lee's wing bound and parameter bounds; the
Newey-West lag rule has a floor of one lag. Every other number, interval,
count, date, and percentage matches the artifacts, including the S_3
sensitivity blocks (lower bounds 0.754 to 0.800) and the carry-only check,
which closes 8.5% of the C0 median gap. The manifest now hashes the paper;
study-v1 and study-v2-locked unmoved.

