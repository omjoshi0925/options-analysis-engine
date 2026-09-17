# Research plan: study v2

Date: 2026-09-08
Status: pre-registered. Written after the v1 study was frozen (tag `study-v1`, commit b41237d; report corrections at ee8ce3c) and before any change to model, baseline, or evaluation code. The commit that adds this file is its timestamp. Deviations are recorded in section 10 and in docs/NOTEBOOK.md, never edited in place.

## 1. Question

The v1 study found that a ridge-learned adjustment to a realized-volatility baseline lowered out-of-sample pricing RMSE on SPY and AAPL end-of-day chains in every calendar year from 2020 to 2026 (median 10.4% per fold across 1,056 folds), with significance that was decisive under the naive Diebold-Mariano test, borderline under Newey-West, and positive under the circular block bootstrap at every block length tested. Both the baseline and the model priced under a constant risk-free rate of 4% (`rate: 0.04` in config/eod-full.json; recorded as `r` on every v1 observation in docs/results/full-history-v2/observations-with-exclusions.csv.gz and in each snapshot's metadata.json) and constant dividend yields (SPY 1.4%, AAPL 0.5%) across a period in which the 3-month Treasury rate moved from near zero to above five percent.

Question: does the learned adjustment capture strike and maturity structure in implied volatility, or does it compensate for the incorrect interest-rate and dividend assumptions that both methods share?

Two hypotheses, not mutually exclusive:

- H-carry. The v1 improvement is mostly absorption of carry misspecification by the model's maturity, carry, and symbol features. Prediction: under historically appropriate r and q, the improvement over the correspondingly corrected baseline shrinks by more than half.
- H-structure. The improvement reflects volatility structure that a flat baseline lacks. Prediction: the improvement survives carry correction but shrinks or disappears against a baseline that already carries the previous session's smile.

## 2. Data and fixed evaluation sets

Source, tier, and quality gates are unchanged from v1: DoltHub `post-no-preference/options` and `post-no-preference/stocks`, the `daily_eod` tier, quotes stamped at the XNYS close, baselines computed from strictly prior available sessions using the close-to-close realized-volatility (last 60 close-to-close returns of the underlying bar series; `baseline_source` = `dolt_prior_60_session_close_to_close` on every v1 observation in docs/results/full-history-v2/observations-with-exclusions.csv.gz and in each snapshot's metadata.json; `baseline_estimator: close_to_close` and `history_window: 60` in config/eod-full.json) estimator. Symbols are SPY and AAPL; the source holds no QQQ rows. The source lacks 664 of 1,841 calendar sessions in the span, so "prior session" throughout this plan means the previous session present in the store, and the gap in calendar days is recorded per observation.

New external inputs, each committed as a CSV with its SHA-256 in docs/results/manifest.json:

- Risk-free rate: FRED series DGS3MO (3-month constant-maturity Treasury), downloaded from https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO without an account. The rate applied to session t is the most recent observation dated strictly before t, converted to a continuously compounded rate r = ln(1 + y). Sensitivity (exploratory): a maturity-matched rate interpolated across DGS1MO, DGS3MO, DGS6MO, and DGS1.
- Dividend yield: per-symbol trailing-12-month cash distribution yield q_t = D_t / S_{t-1}, where D_t is the sum of distributions with ex-dates in the 365 days ending at t-1, taken from the issuers' public distribution histories. Sensitivity (exploratory): the yield implied by put-call parity on at-the-money pairs at t-1 given r_t.
- VIX: FRED series VIXCLS, used only for the exploratory regime breakdowns in section 5.

Fixed evaluation set for Design A: an observation is evaluated only if it passes the v1 quality gates and prices without failure under all four carry configurations in section 3. The set is written once to docs/results/v2/observation-set-A.csv (observation keys plus a hash of the file) and reused by every Design A run. Counts dropped by this intersection rule are reported by reason. Design B uses the subset of set A for which a prior-session implied volatility exists for the contract or its interpolation (section 4), written to observation-set-B.csv. Sessions and fold boundaries are identical across every run: rolling window, 120-session minimum, 250-session maximum, 1-session gap, per-fold hyperparameter reselection over the v1 grid. No observation is excluded on the basis of its loss.

## 3. Design A: carry robustness (confirmatory)

A 2 x 2 factorial on set A with identical folds:

| Run | Rate | Dividend |
|---|---|---|
| C0 | constant (v1) | constant (v1) |
| C1 | historical | constant (v1) |
| C2 | constant (v1) | historical |
| C3 | historical | historical |

C0 on set A is the control. It will differ slightly from the frozen v1 numbers because set A is an intersection; both are reported, and C0 must reproduce v1 up to the drop explained by the intersection before any other run is interpreted.

In each run the baseline is the v1 realized-volatility baseline priced under that run's r and q, and the model is the v1 feature set and estimator with its carry inputs set to that run's r and q. Nothing else changes.

Quantities, all at the session level:

- L_base,k,t and L_model,k,t: session RMSE of the pricing error under configuration k, as defined in walkforward.py at study-v1, unchanged.
- rho_k,t = 1 - L_model,k,t / L_base,k,t: relative improvement.
- d_k,t = L_base,k,t - L_model,k,t: loss differential.
- Delta_k = median over t of rho_k,t. S_k = Delta_k / Delta_0: the fraction of the v1 improvement that survives correction k. The primary estimand is S_3.
- Carry-only check: does correcting carry in the baseline alone close the gap? Compare the median of L_base,3,t with the median of L_model,0,t.

Decision rule, fixed now:

- Compensation dominant if S_3 < 0.5 and the upper bound of its 95% interval is below 0.75.
- Structure dominant if S_3 >= 0.75 and the lower bound of its 95% interval is above 0.5.
- Otherwise mixed or inconclusive. I report S_1, S_2, and S_3 with intervals and do not pick a side.
- Separately, if the 95% interval for the mean of d_3,t includes zero, the v1 improvement did not survive carry correction. That is a negative result and becomes the headline of the writeup.

## 4. Design B: stronger baselines

All Design B runs use configuration C3. Information available at the prediction cutoff for every method: everything up to and including the close of the prior available session t-1, plus the contemporaneous inputs required to price at t (S_t, K, T, r_t, q_t). No method sees any quote from session t.

- B1, prior-session implied volatility: for each contract at t, sigma is the implied volatility of the same contract (symbol, expiry, strike, type) inverted from the t-1 mid under r and q. If the contract is absent at t-1, sigma is linearly interpolated in strike within the same expiry at t-1; if the expiry is absent, the observation is excluded from set B.
- B2, prior-session SVI: for each expiry slice at t-1, fit raw SVI (Gatheral) total variance in log-moneyness of the forward by vega-weighted least squares to the t-1 mid IVs, then evaluate at t's strikes and forward. Fits that fail convergence or the butterfly check fall back to B1 for that slice and are counted.
- M(RV): the v1 model, unchanged. M(B1) and M(B2): the same learner refit with B1 or B2 as its base volatility, so the adjustment is learned relative to the previous smile.

Comparisons:

1. Primary (confirmatory): M(RV) versus B1. The claim "the learned model adds value beyond a credible simple competitor" requires the 95% block-bootstrap interval for the mean of L_B1,t - L_M(RV),t to lie entirely above zero and the median relative improvement to be positive.
2. Secondary: M(RV) versus B2; M(B1) versus B1; M(B2) versus B2. Each is reported with the same statistics, and the label "adds value" is attached only where the interval excludes zero.

If B1 beats M(RV), the v1 model captured structure that a flat baseline lacks but no more than persistence of the previous smile provides, and the value claim is downgraded to that statement.

## 5. Design C: attribution (exploratory)

Pre-specified list, run under C3 for M(RV):

- Ablations, one at a time: remove the moneyness features; remove the maturity interactions; remove the symbol indicator (with two symbols this is a single SPY/AAPL effect, not a group). For each, report Delta and the interval for the change in mean differential relative to the full model.
- Breakdowns of d_3,t and rho_3,t: by symbol; by maturity bucket (30 days or fewer, 31 to 90, more than 90 calendar days); by moneyness bucket (terciles of |log(K/F)|); by VIX regime (terciles of VIXCLS at t-1 over the evaluation window); by gap in days to the prior available session.

Everything in this section is exploratory. Intervals are reported without multiplicity adjustment and no claim from it is confirmatory. Any further cut chosen after inspecting results is labeled as such in the notebook and in the paper.

## 6. Dependent observations and inference

Contracts within a session share the underlying, the regime, and the training window, so all losses are aggregated to the session before any inference. Sessions are serially dependent: the v1 lag-1 autocorrelation of d_t was 0.87 and adjacent folds share 249 of 250 training sessions. Inference on any session-level series:

- Primary: circular block bootstrap over available sessions (not calendar days), block length 21, 10,000 replicates, seed 20260908, percentile 95% interval. Sensitivity at block lengths 10, 63, and 126.
- Paired comparisons across configurations or methods resample the same blocks for both series, so every ratio and difference is computed within each replicate.
- Reported for continuity with v1 but not used for decisions: Diebold-Mariano with the Harvey-Leybourne-Newbold correction, and Newey-West with 6 lags.
- Multiplicity: the confirmatory comparisons are S_3 (Design A) and M(RV) versus B1 (Design B). No adjustment is applied to these two; everything else is exploratory and labeled so.

## 7. Design D: fresh evaluation (locked)

After Designs A to C are complete and written up, the code, configuration, feature set, and hyperparameter grid of the chosen model are frozen at tag `study-v2-locked`, with docs/LOCK.md recording hashes and the protocol below. Nothing in this section runs before that tag exists.

Fresh data are sessions dated strictly after the lock date, arriving through the same DoltHub EOD workflow. For each new session t:

1. Import the underlying close S_t from the stocks database only.
2. Form the prediction set: contracts present at t-1 that have not expired. Price each under the locked model, under B1, and under the RV baseline, using S_t, r_t, q_t, and prior-session information only. Write predictions-{t}.csv with a UTC timestamp and its SHA-256, and commit.
3. Only then import the option chain for t and score the predicted contracts that appear in it. Contracts that appear at t but were not in the prediction set are not scored.

The separation between inputs and targets is physical: the chain file for t is not read until the prediction commit exists. Sample: the first 60 available sessions after the lock, or all sessions available by 2027-03-31, whichever comes first, with no interim stopping based on results. Inference follows section 6, and the interval is reported at whatever width the sample supports. Secondary, if the source holds a symbol untouched by any development work: out-of-symbol transfer with the symbol effect at its reference level, labeled as transfer rather than as a pre-specified test.

## 8. Interpreting negative or inconclusive results

- If the interval for C3's mean differential includes zero: the v1 result was carry compensation. The paper reports this as its main finding, and the engine's contribution is a pipeline that detected its own artifact.
- If the improvement survives C3 but B1 beats M(RV): the adjustment is a weak proxy for smile persistence. It is reported as such, and M(B1) versus B1 becomes the relevant test of incremental value.
- If M(B1) versus B1 includes zero: no incremental value beyond persistence. Reported.
- If S_3's interval spans both decision thresholds: inconclusive. I report the interval and the bootstrap standard error, state the number of sessions that would be needed to reach a threshold at that standard error, and do not re-run with other settings to move it.
- If the fresh evaluation disagrees with the backtest: the backtest estimate is labeled optimistic and both are reported with their intervals.

No run is dropped and no setting is changed after seeing results, except through a dated amendment in section 10.

## 9. Engine changes implied (reference only, not part of the pre-registration)

- Rate and dividend series as configurable inputs with strictly-prior as-of alignment (v3.3).
- Frozen observation sets written once and reused by walk-forward (v3.3).
- B1 and B2 baselines with fallback accounting, and refit-on-baseline support (v3.4).
- Ablation flags and breakdown reports (v3.5).
- predict-locked and score-locked commands for Design D (v4.0).

## 10. Amendments

Entries are appended with date, reason, and what changed. Nothing above is edited.

### Amendment 1, 2026-09-08

Reason: the fill-and-verify pass at commit fd50e25 found three statements about v1 that do not match the frozen code and one definitional ambiguity. No design, threshold, or decision rule changes. Recorded before any code change for v3.3.

1. Section 3, loss definition. L_base,k,t and L_model,k,t are the session mean squared spot-normalized pricing error, exactly as computed in walkforward.py at study-v1. The differential d_k,t = L_base,k,t - L_model,k,t is in those squared units and is the series used by the block bootstrap, both Diebold-Mariano tests, and the win rate, as in v1. The relative improvement rho_k,t = 1 - sqrt(L_model,k,t) / sqrt(L_base,k,t) is in RMSE terms, matching the v1 per-fold improvement column, so Delta_k and S_k keep their meaning. The lag-1 autocorrelation of 0.87 cited in section 6 refers to the squared-loss differential.

2. Section 6, Newey-West lags. The lag count follows the v1 rule floor(1.5 * n^(1/3)), where n is the number of evaluated sessions in the sample: 15 for the 1,056-session full-history sample. Six lags applied only to the 83-fold SPY 2023 run.

3. Section 2, prior session. The "previous session present in the store" definition applies to option-chain information only: B1 and B2 inputs, the parity-implied dividend sensitivity, and the gap covariate. The realized-volatility baseline window is the last 60 close-to-close returns of the underlying bar series from the stocks database (about 2,075 bars per symbol, nearly complete), unchanged from v1, and is not affected by option-session gaps.

4. Section 1, per-year positivity. "Positive in every calendar year" holds under the v1 report's per-year ratio-of-means definition. The plan's Delta_k is the median of per-fold RMSE ratios; under that definition the mean per-fold improvement in v1 is negative in 2021 and 2023. Per-year breakdowns in Design C report both the ratio-of-means and the per-fold median so the two are not conflated.

### Amendment 2, 2026-09-08: Data provenance

Reason: Stage 1 of v3.3 retrieved the external inputs named in section 2 and found three points where the retrieval had to differ from the literal description. No estimand, threshold, or rule changes.

1. AAPL ex-dates come from the DoltHub `post-no-preference/stocks` dividend table matched to the issuer's record dates, because Apple publishes record dates only. Amounts remain the issuer's declared values on the as-traded basis, with the 2020-08-31 4:1 split applied in the series module so that each dividend is on the share basis of the price it is divided by.
2. SPY amounts come from State Street's family-wide ETF Historical Distributions workbook filtered to SPY, cross-checked against DoltHub on every date and amount.
3. FRED DGS3MO was retrieved with curl's default User-Agent; requests imitating a browser received no response.

Files, hashes, timestamps, and the cross-check results are in data/external/PROVENANCE.md.

### Amendment 3, 2026-09-13

Reason: Stage 2 of the v3.3 implementation (commits 2bafa6d, a4fad8c, 96d9b43) and its review found one interaction between the v1 estimator and dated carry inputs that would differ between the arms of Design A, and four points where the implementation had to interpret or extend the text above. Recorded at CHECKPOINT 2, after the C0 control run and before C1, C2, or C3 run. No estimand, threshold, or decision rule changes.

1. Section 3, support guard. The v1 estimator replaces its learned volatility with the baseline for rows whose carry inputs fall outside the training window's range plus a 10% margin. Under constant carry that range has zero width and the guard never fires; under the historical rate it would fire on 21 of the 1,056 evaluated sessions (17 in the 2022 hiking cycle, 4 in late 2025), forcing rho and d to exactly zero in C1 and C3 only. Since the rate and yield enter the model only through the linear features r*T and q*T, the guard's r and q keys are removed for every configuration; the guard on maturity, baseline volatility, log-moneyness, and symbol is unchanged. This is a no-op for v1 and for C0, whose numbers are reproduced exactly on the amended code, and it is covered by a regression test. Every run's significance.json still records the folds with partial or zero learned coverage.

2. Section 3, learning target. Under configuration k the model's target is the implied volatility of the session-t mid inverted under r_k,t and q_k,t, so target, carry features, and pricing share one carry; constant v1 carry reproduces every stored target exactly. Section 2's "prices without failure" therefore includes identification of that target within the v1 range under every configuration. Set A drops 6,742 of 260,296 eligible rows (2.6%) on this rule alone: in-the-money short-dated puts whose mid sits below the lower bound at a near-zero rate, 62% in 2020 to 2021; no session is lost and the fold boundaries are the v1 ones. The composition is recorded in docs/results/v2/observation-set-A.drops.json, and the writeup reports C0 on set A against the frozen v1 by calendar year as well as overall.

3. Section 2, rate conversion. The FRED value y is a percentage; the applied conversion is r = ln(1 + y/100). Missing days in the download are blank and are skipped like ".", so a holiday session takes the last quoted business day.

4. Section 2, coverage of the dividend inputs. The declared distribution history runs from 2018-01-01 to the 2026-09-09 retrieval; a 365-day window that starts before or ends after it is refused, as is a rate quote or underlying bar more than 10 calendar days old. None of these refusals occurs on any stored session, so they change no number in Design A; they exist so that later extensions cannot sum an incomplete history silently.

5. Section 3, configuration files. config/v2/C0.json to C3.json sit one directory below config/eod-full.json, so their data_root reads ../../data/eod-live-full rather than ../data/eod-live-full and resolves to the same store; rate and dividend are the only other differences.

### Amendment 4, 2026-09-13

Reason: Design B (section 4) leaves three operational points open that the v3.4 implementation has to fix before any run. Recorded before any Design B code was written. No estimand, threshold, or decision-rule changes.

- B1 inversion carry. The prior-session implied volatility is inverted from the t-1 mid using r_{t-1}, q_{t-1}, S_{t-1}, and time to expiry measured from t-1. The resulting sigma is applied at t with r_t, q_t, S_t, and time to expiry from t. Rationale: the mid was observed under t-1 conditions, and using t's carry to invert a t-1 price would mix regimes.
- Set B control. M(RV) is rerun on set B so the effect of restricting from set A to set B is visible before any B1 or B2 comparison is interpreted, exactly as C0 on set A controlled for the A intersection.
- SVI fallback. Slices whose fit fails convergence or the butterfly check fall back to B1 and are counted; if fallbacks exceed 20% of slices, B2 is reported as a fallback-contaminated benchmark and not used for the secondary claim.

### Amendment 5, 2026-09-14

Reason: specified after the Design B result was known, so everything here is exploratory and labeled as such; no estimand, threshold, or decision-rule changes. Prior-session persistence benefits mechanically from unchanged quotes: when a contract's mid at t equals its mid at t-1, B1 reprices the same number under nearly the same inputs, and the paper must state what share of B1's advantage comes from that.

- Stale-quote diagnostic (Design B, exploratory). Over set B: the fraction of observations whose mid at t equals the same contract's mid at t-1 exactly; the distribution of |mid_t - mid_{t-1}| / mid_{t-1}; both broken out by symbol, maturity bucket, moneyness tercile, and the gap in days to the prior available session. The primary comparison M(RV) versus B1 and the incremental comparison M(B1) versus B1 are recomputed on the subset with mid_t strictly different from mid_{t-1}, with the same folds (models trained exactly as in the pre-registered runs; only the evaluation rows are restricted) and the same bootstrap settings, and reported alongside the full-set-B figures without replacing them. B1's own median session RMSE is reported on the unchanged-mid and changed-mid subsets so the size of the mechanical advantage is visible. Outputs: docs/results/v2/design-b/stale-quote-diagnostic.json and a section of the Design B report.
- Design C reference methods. The section 5 breakdowns of d and rho by symbol, maturity bucket, moneyness bucket, VIX regime, and gap are reported against both the RV baseline and B1 as reference methods, because the Design B outcome makes "where the model fails" a question about B1, not about the flat baseline. The list of breakdowns, their exploratory status, and the absence of multiplicity adjustment are unchanged.

### Amendment 6, 2026-09-15

Reason: the Design C breakdowns (section 5) found the source's maturity coverage narrower than the bucket definition assumed. Recorded at the Design C CHECKPOINT, after the breakdowns were computed and before the report was written. Exploratory scope only: no estimand, threshold, or decision-rule changes, and no pre-registered number is altered.

- Maturity coverage. The DoltHub option chains behind the observation store list two to four expirations per symbol and session and none beyond 67 calendar days, so section 5's "more than 90 calendar days" bucket is empty in every breakdown and the realized buckets are 30 days or fewer and 31 days to the maximum (67 in set A, 65 in set B). The exact maximum time to expiry, measured as the walk-forward measures it between the session close and the expiration close (the fractional hour is the daylight-saving offset), is 66.958 days (T = 0.18345 years) in set A and 65.042 days (T = 0.17820 years) in set B, the same over each whole set and over its evaluated rows; the minimum is 10.000 days in both, and no row in the imported store exceeds the set A maximum. The study therefore covers short-dated options only, and no term-structure claim can be made from it. Design C reports the empty bucket as empty rather than redefining the buckets after the fact; the observed range is recorded per entry in docs/results/v2/design-c/breakdowns.json.

### Amendment 7, 2026-09-15

Reason: section 7 freezes the study before any fresh session is scored, and the expectations for that evaluation belong on record before the first prediction file exists. Derived from the Design B and Design C results (docs/results/v2/design-b/comparison.json and docs/results/v2/design-c/), recorded at the lock (tag study-v2-locked, docs/LOCK.md) and fixed before any fresh session is scored. No estimand, threshold, or decision-rule changes: inference on the fresh sample follows section 6 at whatever width the sample supports, and the section 7 sample rule stands (the first 60 available sessions after the lock date, or all sessions available by 2027-03-31, whichever comes first, with no interim stopping on results). The prediction file for each fresh session carries the RV baseline, B1, M(RV), and M(B1) prices, so every expectation below can be read from the same sample; operational interpretations of section 7 are recorded in docs/LOCK.md.

Pre-registered expectations for the fresh evaluation:

1. B1 beats M(RV) on the primary loss. Expected direction: the mean of L_B1 - L_M(RV) is negative with its 95% block-bootstrap interval below zero, and M(RV)'s session win rate against B1 is under 0.15.
2. M(B1) versus B1 is indistinguishable from zero. Expected: the interval for the mean of L_B1 - L_M(B1) includes zero at every block length (21, and the sensitivity blocks 10, 63, and 126 where the sample allows them). This comparison is expected to be null, and confirming the null is the result of the test, not a failure of the evaluation.
3. M(RV) versus the RV baseline stays positive in median rho, with the advantage concentrated in high-VIX sessions and at maturities of 31 days or longer. High-VIX sessions are those whose strictly-prior VIXCLS exceeds the Design C upper tercile cut point (20.16, docs/results/v2/design-c/breakdowns.json); the maturity split is at 30 calendar days, the only split the source's coverage realizes (Amendment 6). The concentration statement is directional and is read with the section 5 caveats: no multiplicity adjustment and no confirmatory claim from the cells.

Stating these in advance means the fresh evaluation is judged against declared directions rather than against whichever outcome appears: a sample that contradicts expectation 1 or 3 is reported as such, and a sample that confirms expectation 2 is the null result the design anticipates.

### Amendment 8, 2026-09-17

Reason: an outside review flagged that the engine prices American-style contracts (SPY and AAPL options) with the European closed form. Specified after every pre-registered result was known, so everything under this amendment is exploratory and labeled so; no estimand, threshold, or decision-rule changes, and no reported number is replaced. It exists because B1's sigma is inverted from a t-1 mid under the European formula and repriced under the same formula at t, so an error in the pricing engine largely cancels for B1, whereas M(RV)'s sigma does not come from an option price and its pricing error does not cancel; the European engine may therefore advantage B1 over M(RV) asymmetrically.

- Diagnostic. For every evaluated observation of sets A and B, the early-exercise premium on the CRR binomial tree of options_engine.american (200 steps) at the study's S, K, T, r, q, at the quote's own European implied volatility and at each method's sigma, as a fraction of the mid, broken out by option type, moneyness tercile, maturity bucket, symbol, and rate regime (2020-21 near-zero against 2022 onward), with the share of observations whose premium exceeds the quote's tick. The cancellation test: B1 inverted from the t-1 mid and repriced at t on the tree against the same under the European formula, compared with M(RV) repriced on the tree at its own sigma. The Design B primary and incremental comparisons restricted to observations whose premium is below the tick, on the same folds and bootstrap settings, reported beside the pre-registered numbers. Outputs: docs/results/v2/early-exercise-diagnostic.json and a section of the Design B report.
- Pricing engine. Any change to the pricing engine is deferred to a future study. The locked model (docs/LOCK.md) is not modified, the fresh evaluation continues under the European formula as locked, and the diagnostic touches no locked module.
- Reviewer extract. A deterministic stratified sample of the evaluated observations is added under docs/results/v2/extract/ for inspection; no reported number comes from it.

### Amendment 9, 2026-09-17

Reason: the first fresh session, 2026-09-16, was predicted with the prior available session 2026-09-04 because the sessions between the last stored session and the lock date had been kept out of the store under a reading of the predict-before-import rule that applied it to every session. Decided after the 2026-09-16 result was seen, and recorded as such. No estimand, threshold, or decision-rule change.

- Sessions dated on or before the lock date (2026-09-15) may be imported at any time. They are ineligible for Design D scoring and serve only as prior-session information for later predictions: the training windows and the contracts, prior quotes, and B1 volatilities of the prior available session. The predict-before-import rule of section 7 applies to scorable sessions only, those dated strictly after the lock date, for which the chain is still not read until that session's prediction file is committed.
- The 2026-09-16 session stands as scored: 47 contracts against a B1 taken from 2026-09-04, a 12-day gap, noted in docs/FRESH_EVAL.md. It is not rescored and its prediction file is not replaced.
- The change favors B1, the competitor, not the locked model: with the 2026-09-08 to 2026-09-15 sessions in the store, later fresh sessions inherit a prior session one day old rather than twelve, which is the condition under which B1 beat M(RV) in Design B. The locked model's training windows also move forward by the same sessions, as they would under the ordinary flow of the source.

