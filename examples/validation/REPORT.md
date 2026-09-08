# Options analysis report

**SYNTHETIC DEMONSTRATION - NOT MARKET EVIDENCE**

Raw contracts: 209. Accepted: 184. Rejected: 25.

Errors are midpoint minus the independent baseline price, in currency units per share.
Contract-specific IV reconstruction is an inversion check, not independent pricing accuracy.

## Quote audit

Exclusion reasons can overlap.

- wide_spread: 22
- invalid_quote: 16
- crossed_market: 1
- invalid_volume: 1
- expired: 1
- maturity_filter: 1

## Baseline comparison

| Metric | Value |
|---|---:|
| n | 184 |
| mae | 0.284551 |
| rmse | 0.488239 |
| median_error | 0.0264219 |
| mean_error | 0.205106 |
| mape_pct | 12.8184 |
| n_mape | 174 |
| mape_min_mid | 0.1 |
| within_bid_ask_pct | 42.9348 |
| american_mae | 0.34202 |
| american_rmse | 0.525085 |
| american_within_bid_ask_pct | 31.5217 |
| mean_early_exercise_premium | 0.0678931 |

Baseline inputs (annual decimal units):

symbol  baseline_sigma    r    q
DEMO_A            0.20 0.04 0.01
DEMO_B            0.28 0.04 0.01

MAPE excludes midpoint < 0.1; n_mape records its denominator. All accepted quotes remain in MAE/RMSE, including IV failures.
Pooled dollar errors are scale dependent; compare asset/type/expiry groups before pooling assets.

## IV solver diagnostics

- brent: converged=183, lower_bound_limit=1
- newton: converged=183, lower_bound_limit=1
- Newton-to-Brent fallbacks: 0.
- Identified Brent solves: 183. Max absolute repricing residual: 8.52651e-13.
- Max numerical formula parity residual: 1.42109e-14.
- Accepted midpoints outside European bounds: 0.

## Where does the baseline perform best and worst?

Ranked by descriptive MAE within asset/type/expiry groups with at least 5 quotes; this is not a forecast or causal test.

- Lowest MAE: DEMO_A / put / 2026-09-18, MAE 0.0162207, n=12.
- Highest MAE: DEMO_B / call / 2026-12-18, MAE 0.790865, n=17.

## Early-exercise premium (American baseline)

The American baseline prices each quote on a CRR binomial tree with the same independent volatility;
the premium is the American minus the European tree value, so shared discretization error cancels.
A premium only applies to contracts that permit early exercise; the synthetic chain is generated as European.

- calls: n=90, mean premium 0, max premium 0, European MAE 0.290774, American MAE 0.291269, within-spread European 34.4% / American 33.3%
- puts: n=94, mean premium 0.132897, max premium 0.812212, European MAE 0.278592, American MAE 0.390611, within-spread European 51.1% / American 29.8%
- Max absolute tree discretization error at 184 quotes: 0.0127709.

## Implied forward, rate, and yield from put-call parity

Per asset and expiry, call-minus-put midpoints are regressed on strike across matched pairs (implied_forward.csv).
The slope implies the discount factor and rate; the intercept implies the discounted forward and the dividend yield.
Compare these with the assumed r and q. American early exercise, stale quotes, and wide spreads bias the fit.

- DEMO_A 2026-09-18: n=6, implied r 0.0400 (assumed 0.0400), implied q 0.0100 (assumed 0.0100), forward 100.0826, R² 1.000000
- DEMO_A 2026-10-16: n=15, implied r 0.0400 (assumed 0.0400), implied q 0.0100 (assumed 0.0100), forward 100.3132, R² 1.000000
- DEMO_A 2026-12-18: n=17, implied r 0.0400 (assumed 0.0400), implied q 0.0100 (assumed 0.0100), forward 100.8343, R² 1.000000
- DEMO_B 2026-09-18: n=10, implied r 0.0400 (assumed 0.0400), implied q 0.0100 (assumed 0.0100), forward 175.1445, R² 1.000000
- DEMO_B 2026-10-16: n=17, implied r 0.0400 (assumed 0.0400), implied q 0.0100 (assumed 0.0100), forward 175.5480, R² 1.000000
- DEMO_B 2026-12-18: n=17, implied r 0.0400 (assumed 0.0400), implied q 0.0100 (assumed 0.0100), forward 176.4600, R² 1.000000

## Moneyness, maturity, and liquidity

metrics.csv reports fixed moneyness, tenor, IV, volume, open-interest, and relative-spread groups with sample sizes.
plots/market_diagnostics.png displays these relationships. Correlation with liquidity does not isolate transaction costs or establish causation.
smile_summary.csv reports local IV slopes versus ln(S/K) over |ln(S/K)| <= 0.15. Positive slope on this axis corresponds to IV increasing toward lower strikes.
Provider-IV differences may reflect different spot, rate, dividend, exercise, or quote conventions; provider IV is not ground truth.

## Assumptions and limits

- Constant volatility: a nonflat IV curve is inconsistent with one common BSM volatility under the other maintained assumptions.
- Constant rates and continuous dividend yield: r and q are explicit scenario inputs; discrete dividends and a term structure are not modeled.
- European exercise: American early-exercise effects can contribute to residuals. European bounds/parity failures are not proof of market arbitrage.
- Continuous trading and frictionless markets: spreads, discrete hedging, transaction costs, and asynchronous/delayed observations matter.
- Lognormal price levels and continuous paths: jumps, fat-tailed returns, and stochastic volatility are omitted; one snapshot cannot identify their separate effects.
- Yahoo capture time is not bid/ask quote time. lastTradeDate measures trade age only. PM expiry at the configured hour is an assumption; no holiday/early-close calendar is applied.
- Historical realized volatility is a backward-looking independent comparator, not a risk-neutral forecast. A fixed volatility is a declared scenario.
- BSM remains useful as a transparent benchmark, IV coordinate system, and local sensitivity model, even when assumptions fail.

## Next empirical step

Collect multiple dated snapshots across assets and market regimes; inspect spot/quote synchronization, rate/dividend sensitivity, and exclusion counts before interpreting market performance.

The synthetic data deliberately contain a volatility skew and known bad quotes. Every result above demonstrates software behavior only.
