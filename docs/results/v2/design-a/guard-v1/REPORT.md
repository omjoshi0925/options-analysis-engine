# Design A: carry robustness (C0 control, C3-guard-v1 full correction)

1056 evaluated sessions from 2020-10-23 to 2026-09-04, identical across runs. Intervals: paired circular block bootstrap, block 21, 10,000 replicates, seed 20260908, percentile 95%.

| Run | Folds | Median rho | Mean d | Win rate | Median baseline MSE | Median model MSE | Coverage mean | Zero-coverage folds | DM (HLN) | Newey-West |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C0 | 1056 | 0.1086 | 4.732e-04 | 0.664 | 1.419e-05 | 1.185e-05 | 0.9970 | 0 | 3.67 (p = 0.00025) | 1.22 (p = 0.22, 15 lags) |
| C1-guard-v1 | 1056 | 0.1031 | 4.752e-04 | 0.635 | 1.404e-05 | 1.164e-05 | 0.9771 | 21 | 3.66 (p = 0.00026) | 1.22 (p = 0.22, 15 lags) |
| C2-guard-v1 | 1056 | 0.1060 | 4.732e-04 | 0.665 | 1.419e-05 | 1.180e-05 | 0.9970 | 0 | 3.67 (p = 0.00025) | 1.22 (p = 0.22, 15 lags) |
| C3-guard-v1 | 1056 | 0.1070 | 4.755e-04 | 0.644 | 1.399e-05 | 1.146e-05 | 0.9771 | 21 | 3.67 (p = 0.00026) | 1.22 (p = 0.22, 15 lags) |

## S_k = median rho_k / median rho_0

| k | S_k | 95% interval (block 21) | block 10 | block 63 | block 126 |
|---|---:|---:|---:|---:|---:|
| C1-guard-v1 | 0.950 | [0.652, 1.221] | [0.699, 1.187] | [0.642, 1.294] | [0.648, 1.332] |
| C2-guard-v1 | 0.977 | [0.891, 1.121] | [0.903, 1.105] | [0.877, 1.144] | [0.884, 1.141] |
| C3-guard-v1 | 0.986 | [0.755, 1.273] | [0.793, 1.236] | [0.744, 1.355] | [0.774, 1.371] |

## Carry-only check and the full-correction differential

- median(L_base,C3-guard-v1) - median(L_model,C0) = 2.136e-06, 95% interval [2.581e-07, 3.859e-06] (median baseline MSE under C3-guard-v1 1.399e-05; median model MSE under C0 1.185e-05).
- Mean d_1 = 4.755e-04, 95% interval [7.108e-06, 1.405e-03]; block 10: [9.813e-06, 1.248e-03]; block 63: [4.800e-06, 1.408e-03]; block 126: [5.200e-06, 1.403e-03].

## Decision (section 3 rule, applied mechanically)

**structure dominant**: S_3 = 0.986 with 95% interval [0.755, 1.273]: structure dominant.

Compensation dominant if S_3 < 0.5 and the upper bound is below 0.75; structure dominant if S_3 >= 0.75 and the lower bound is above 0.5; otherwise mixed or inconclusive. Separately, a mean d_3 interval that includes zero means the v1 improvement did not survive carry correction.

Diebold-Mariano and Newey-West values are reported for continuity with v1 and are not used for decisions.
