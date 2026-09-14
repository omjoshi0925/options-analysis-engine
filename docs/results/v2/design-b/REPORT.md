# Design B: stronger baselines on set B

1005 evaluated sessions from 2020-11-16 to 2026-09-04, identical across the five runs. Intervals: paired circular block bootstrap, block 21, 10,000 replicates, seed 20260908, percentile 95%.

| Comparison | Mean L_baseline - L_model | 95% interval (block 21) | block 10 | block 63 | block 126 | Median relative improvement | Win rate | DM (HLN) | Newey-West | Label |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| M(RV) vs B1 (primary) | -1.692e-05 | [-2.407e-05, -1.137e-05] | [-2.35e-05, -1.20e-05] | [-2.52e-05, -1.03e-05] | [-2.47e-05, -1.01e-05] | -1.8900 [-2.178, -1.609] | 0.054 | -10.37 (p = 5.4e-24) | -5.28 (p = 1.6e-07, 15 lags) | baseline wins |
| M(RV) vs B2 | -1.316e-05 | [-2.041e-05, -7.642e-06] | [-1.96e-05, -8.36e-06] | [-2.18e-05, -6.40e-06] | [-2.15e-05, -6.16e-06] | -0.4545 [-0.583, -0.353] | 0.154 | -8.25 (p = 4.8e-16) | -4.12 (p = 4.2e-05, 15 lags) | baseline wins |
| M(B1) vs B1 | 4.104e-07 | [5.393e-08, 8.397e-07] | [9.14e-08, 7.72e-07] | [-4.54e-08, 1.01e-06] | [-9.78e-08, 1.17e-06] | -0.0119 [-0.026, -0.001] | 0.463 | 2.76 (p = 0.0059) | 2.18 (p = 0.029, 15 lags) | adds value |
| M(B2) vs B2 | -4.825e-06 | [-8.200e-06, -2.502e-06] | [-7.60e-06, -2.90e-06] | [-9.31e-06, -1.84e-06] | [-9.76e-06, -1.48e-06] | -0.2382 [-0.307, -0.173] | 0.241 | -6.82 (p = 1.6e-11) | -3.54 (p = 0.00042, 15 lags) | baseline wins |

## Primary claim (section 4 rule, applied mechanically)

**does not hold**: B1 beats M(RV): the v1 model captured structure that a flat baseline lacks but no more than persistence of the previous smile provides; the value claim is downgraded to that statement and M(B1) versus B1 becomes the relevant test of incremental value. M(B1) versus B1 excludes zero above, so the adjustment adds value beyond persistence when learned relative to it.

The claim requires the interval for the mean of L_B1 - L_M(RV) to lie entirely above zero and the median relative improvement to be positive. Secondary labels attach only where the interval excludes zero.

## Caveats on labels that rest on the mean alone

- M(B1) vs B1: labeled by the block-21 interval alone; the median relative improvement is -0.0119, so the mean gain comes from a minority of sessions; the model loses in 53.7% of sessions; the interval includes zero at block lengths 63, 126.

## B2 fallback accounting (Amendment 4)

- SVI slices attempted 4520, fitted 4343, fallback rate 3.9% by reason {'butterfly': 56, 'no_convergence': 3, 'parameter_bounds': 1, 'too_few_strikes': 117}; rows by source {'fallback_b1': 4072, 'svi': 150038}. Fallback-contaminated: False.

## Set B control (Amendment 4)

| Run | Folds | Median rho | Mean d | Win rate | Median baseline MSE | Median model MSE |
|---|---:|---:|---:|---:|---:|---:|
| M(RV) on set B | 1005 | 0.1623 | 2.530e-04 | 0.708 | 1.609e-05 | 1.132e-05 |
| C3 on set A (Design A) | 1056 | 0.1070 | 4.748e-04 | 0.646 | 1.399e-05 | 1.146e-05 |

Diebold-Mariano and Newey-West values are reported for continuity with v1 and are not used for decisions.

## Stale-quote diagnostic (exploratory, Amendment 5)

Of set B's 154,110 observations, 88,408 have the same contract quoted at the prior available session; 892 of those (1.0%; 0.6% of set B) have a mid identical to the prior session's. Among comparable rows |mid_t - mid_(t-1)| / mid_(t-1) has percentiles p10 0.010, p25 0.032, p50 0.096, p75 0.221, p90 0.394.

| Breakdown | Group | Rows | Comparable | Unchanged share of comparable | Median relative change |
|---|---|---:|---:|---:|---:|
| symbol | AAPL | 87,852 | 68,844 | 1.0% | 0.113 |
| symbol | SPY | 66,258 | 19,564 | 1.2% | 0.041 |
| maturity | 31-90d | 81,276 | 45,601 | 1.1% | 0.087 |
| maturity | <=30d | 72,834 | 42,807 | 0.9% | 0.108 |
| moneyness tercile | farthest | 51,370 | 33,192 | 1.3% | 0.059 |
| moneyness tercile | middle | 51,370 | 29,153 | 1.0% | 0.115 |
| moneyness tercile | nearest | 51,370 | 26,063 | 0.7% | 0.139 |
| gap in days | 1 | 63,427 | 36,454 | 1.2% | 0.072 |
| gap in days | 2 | 39,315 | 22,662 | 0.7% | 0.130 |
| gap in days | 3 | 45,644 | 26,135 | 1.1% | 0.095 |
| gap in days | 4 | 2,026 | 1,039 | 0.7% | 0.171 |
| gap in days | 5+ | 3,698 | 2,118 | 0.8% | 0.191 |
| B1 source | interpolated | 65,702 | 0 | n/a | n/a |
| B1 source | same_contract | 88,408 | 88,408 | 1.0% | 0.096 |

Sensitivity: the two Design B comparisons recomputed on evaluation subsets, with the pre-registered training windows and models (only the rows entering each session's loss change) and the same bootstrap settings. The full-set-B figures are the pre-registered ones.

| Subset | Sessions | Comparison | Mean L_baseline - L_model | 95% interval | Median relative improvement | Win rate | Label |
|---|---:|---|---:|---:|---:|---:|---|
| changed-mid | 1004 | M(B1) vs B1 | 5.250e-07 | [7.88e-08, 1.04e-06] | -0.0013 | 0.497 | adds value |
| changed-mid | 1004 | M(RV) vs B1 | -1.895e-05 | [-3.00e-05, -1.11e-05] | -1.5780 | 0.078 | baseline wins |
| not-unchanged-mid | 1005 | M(B1) vs B1 | 4.101e-07 | [5.43e-08, 8.38e-07] | -0.0119 | 0.465 | adds value |
| not-unchanged-mid | 1005 | M(RV) vs B1 | -1.694e-05 | [-2.41e-05, -1.14e-05] | -1.8894 | 0.055 | baseline wins |
| unchanged-mid | 379 | M(RV) vs B1 | -7.768e-06 | [-1.10e-05, -4.76e-06] | -4.8921 | 0.111 | baseline wins |

B1's median session RMSE: changed-mid 1.2551e-03 (1004 sessions, M(RV) 3.2764e-03); full set B 1.1862e-03 (1005 sessions, M(RV) 3.3652e-03); not-unchanged-mid 1.1834e-03 (1005 sessions, M(RV) 3.3645e-03); unchanged-mid 2.7691e-04 (379 sessions, M(RV) 1.7844e-03).

Label changes against the pre-registered labels: none.

