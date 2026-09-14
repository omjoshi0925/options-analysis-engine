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
