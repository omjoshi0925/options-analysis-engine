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
