# Design A: carry robustness (C0 control, C3 full correction)

1056 evaluated sessions from 2020-10-23 to 2026-09-04, identical across runs. Intervals: paired circular block bootstrap, block 21, 10,000 replicates, seed 20260908, percentile 95%.

| Run | Folds | Median rho | Mean d | Win rate | Median baseline MSE | Median model MSE | Coverage mean | Zero-coverage folds | DM (HLN) | Newey-West |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C0 | 1056 | 0.1086 | 4.732e-04 | 0.664 | 1.419e-05 | 1.185e-05 | 0.9970 | 0 | 3.67 (p = 0.00025) | 1.22 (p = 0.22, 15 lags) |
| C1 | 1056 | 0.1036 | 4.742e-04 | 0.637 | 1.404e-05 | 1.164e-05 | 0.9970 | 0 | 3.66 (p = 0.00027) | 1.22 (p = 0.22, 15 lags) |
| C2 | 1056 | 0.1060 | 4.732e-04 | 0.665 | 1.419e-05 | 1.180e-05 | 0.9970 | 0 | 3.67 (p = 0.00025) | 1.22 (p = 0.22, 15 lags) |
| C3 | 1056 | 0.1070 | 4.748e-04 | 0.646 | 1.399e-05 | 1.146e-05 | 0.9970 | 0 | 3.66 (p = 0.00026) | 1.22 (p = 0.22, 15 lags) |

## S_k = median rho_k / median rho_0

| k | S_k | 95% interval (block 21) | block 10 | block 63 | block 126 |
|---|---:|---:|---:|---:|---:|
| C1 | 0.955 | [0.665, 1.230] | [0.709, 1.195] | [0.657, 1.301] | [0.662, 1.343] |
| C2 | 0.977 | [0.891, 1.121] | [0.903, 1.105] | [0.877, 1.144] | [0.884, 1.141] |
| C3 | 0.986 | [0.762, 1.281] | [0.800, 1.242] | [0.754, 1.358] | [0.779, 1.377] |

## Carry-only check and the full-correction differential

- median(L_base,C3) - median(L_model,C0) = 2.136e-06, 95% interval [2.581e-07, 3.859e-06] (median baseline MSE under C3 1.399e-05; median model MSE under C0 1.185e-05).
- Mean d_3 = 4.748e-04, 95% interval [6.320e-06, 1.404e-03]; block 10: [9.124e-06, 1.248e-03]; block 63: [3.985e-06, 1.407e-03]; block 126: [4.227e-06, 1.402e-03].

## Decision (section 3 rule, applied mechanically)

**structure dominant**: S_3 = 0.986 with 95% interval [0.762, 1.281]: structure dominant.

Compensation dominant if S_3 < 0.5 and the upper bound is below 0.75; structure dominant if S_3 >= 0.75 and the lower bound is above 0.5; otherwise mixed or inconclusive. Separately, a mean d_3 interval that includes zero means the v1 improvement did not survive carry correction.

Diebold-Mariano and Newey-West values are reported for continuity with v1 and are not used for decisions.
