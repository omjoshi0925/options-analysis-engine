# Design C: attribution (exploratory)

Exploratory (Research Plan section 5, Amendment 5): no claim in this section is confirmatory, and the intervals carry no multiplicity adjustment.

## Feature ablations

With two symbols the symbol ablation removes one indicator, a single SPY/AAPL contrast, not a group of features.

### M(B1) on set B, reference B1

Exploratory (Research Plan section 5, Amendment 5): no claim in this section is confirmatory, and the intervals carry no multiplicity adjustment.

1005 sessions from 2020-11-16 to 2026-09-04; paired block bootstrap, block 21, 10,000 replicates, seed 20260908.

| Model | Delta (median rho) | Mean d | Win rate | Change in mean d vs full | 95% interval | Change in Delta | 95% interval |
|---|---:|---:|---:|---:|---:|---:|---:|
| full | -0.0119 | 4.104e-07 | 0.463 | | | | |
| without maturity-interactions | -0.0167 | 3.620e-07 | 0.440 | -4.848e-08 | [-8.72e-08, -1.52e-08] | -0.0048 | [-0.0098, -0.0009] |
| without moneyness | -0.0107 | 2.799e-07 | 0.437 | -1.305e-07 | [-2.63e-07, -5.18e-09] | +0.0012 | [-0.0063, +0.0105] |
| without symbol | -0.0106 | 3.595e-07 | 0.461 | -5.089e-08 | [-1.01e-07, -1.41e-08] | +0.0013 | [-0.0027, +0.0044] |

- Without maturity interactions: Delta moves from -0.0119 to -0.0167; the mean differential moves from 4.104e-07 to 3.620e-07 (-11.8%).
- Without moneyness: Delta moves from -0.0119 to -0.0107; the mean differential moves from 4.104e-07 to 2.799e-07 (-31.8%).
- Without symbol: Delta moves from -0.0119 to -0.0106; the mean differential moves from 4.104e-07 to 3.595e-07 (-12.4%).
- The mean differential is dominated by a few high-error sessions: the 10 largest of 1005 sessions carry 90.5% of the sum of d in the full model (median d -3.381e-08 against mean d 4.104e-07; mean without them 3.940e-08). Where Delta crosses zero while the mean differential barely moves, the median describes the typical session and the mean does not.

### M(RV) on set A, reference RV baseline

Exploratory (Research Plan section 5, Amendment 5): no claim in this section is confirmatory, and the intervals carry no multiplicity adjustment.

1056 sessions from 2020-10-23 to 2026-09-04; paired block bootstrap, block 21, 10,000 replicates, seed 20260908.

| Model | Delta (median rho) | Mean d | Win rate | Change in mean d vs full | 95% interval | Change in Delta | 95% interval |
|---|---:|---:|---:|---:|---:|---:|---:|
| full | 0.1070 | 4.748e-04 | 0.646 | | | | |
| without maturity-interactions | 0.0456 | 4.706e-04 | 0.545 | -4.200e-06 | [-6.62e-06, -2.38e-06] | -0.0614 | [-0.1034, -0.0332] |
| without moneyness | -0.1161 | 4.643e-04 | 0.390 | -1.054e-05 | [-1.37e-05, -7.88e-06] | -0.2232 | [-0.2616, -0.1835] |
| without symbol | 0.0775 | 4.724e-04 | 0.626 | -2.426e-06 | [-4.46e-06, -9.19e-07] | -0.0296 | [-0.0529, -0.0064] |

- Without maturity interactions: Delta moves from +0.1070 to +0.0456; the mean differential moves from 4.748e-04 to 4.706e-04 (-0.9%).
- Without moneyness: Delta moves from +0.1070 to -0.1161 and crosses zero; the mean differential moves from 4.748e-04 to 4.643e-04 (-2.2%).
- Without symbol: Delta moves from +0.1070 to +0.0775; the mean differential moves from 4.748e-04 to 4.724e-04 (-0.5%).
- The mean differential is dominated by a few high-error sessions: the 10 largest of 1056 sessions carry 77.5% of the sum of d in the full model (median d 2.703e-06 against mean d 4.748e-04; mean without them 1.079e-04). Where Delta crosses zero while the mean differential barely moves, the median describes the typical session and the mean does not.

## Maturity coverage (Amendment 6)

Exploratory (Research Plan section 5, Amendment 5): no claim in this section is confirmatory, and the intervals carry no multiplicity adjustment.

- M(B1) vs B1 on set B: time to expiry from 10.000 to 65.042 days (T up to 0.17820 years); empty maturity buckets: >90d.
- M(RV) vs B1 on set B: time to expiry from 10.000 to 65.042 days (T up to 0.17820 years); empty maturity buckets: >90d.
- M(RV) vs RV baseline on set A: time to expiry from 10.000 to 66.958 days (T up to 0.18345 years); empty maturity buckets: >90d.

The source lists no expiry beyond 66.958 days to expiry, so the plan's more-than-90-day maturity bucket is empty in every breakdown and the realized buckets are 30 days or fewer and 31 days to that maximum. The study covers short-dated options only, and no term-structure claim can be made from it.

## Breakdowns of d and rho

Exploratory (Research Plan section 5, Amendment 5): no claim in this section is confirmatory, and the intervals carry no multiplicity adjustment.

VIX regime: VIXCLS at the most recent observation strictly before the session, terciles cut at 16.45 and 20.16. Moneyness: |log(K/F)| terciles cut at 0.0557 and 0.1350. Cells with fewer than 30 sessions report counts and point values without an interval.

### M(B1) vs B1 on set B

Exploratory (Research Plan section 5, Amendment 5): no claim in this section is confirmatory, and the intervals carry no multiplicity adjustment.

Reference: the model run's own baseline. 1005 sessions, 142,942 observations; overall median rho -0.0119, mean d 4.104e-07, win rate 0.463.

**gap in days to the prior available session**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 376 | 62,737 | -0.0317 | 7.877e-07 | 0.431 | [+1.18e-07, +1.58e-06] |
| 2 | 295 | 29,448 | -0.0201 | -1.561e-07 | 0.420 | [-4.10e-07, +2.43e-08] |
| 3 | 248 | 40,989 | 0.0150 | 6.668e-07 | 0.540 | [+4.53e-08, +1.57e-06] |
| 4 | 45 | 6,156 | -0.0233 | -1.863e-07 | 0.467 | [-5.67e-07, +2.09e-07] |
| 5+ | 41 | 3,612 | 0.0412 | 1.314e-07 | 0.585 | [-2.08e-08, +2.84e-07] |

**maturity bucket (calendar days to expiry)**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| 31-90d | 950 | 74,700 | -0.0236 | 4.041e-07 | 0.438 | [+1.68e-08, +8.54e-07] |
| <=30d | 784 | 68,242 | -0.0027 | 6.289e-07 | 0.491 | [+1.80e-07, +1.24e-06] |
| >90d | 0 | 0 | n/a | n/a | n/a | none (fewer than 30 sessions) |

**moneyness tercile of |log(K/F)|**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| high | 1005 | 45,767 | -0.0026 | 6.473e-07 | 0.496 | [+1.79e-07, +1.24e-06] |
| low | 1005 | 49,060 | -0.0526 | 5.507e-08 | 0.380 | [-3.12e-07, +4.15e-07] |
| middle | 1005 | 48,115 | 0.0187 | 5.909e-07 | 0.568 | [+2.11e-07, +1.04e-06] |

**symbol**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| AAPL | 980 | 80,050 | -0.0012 | 6.143e-07 | 0.498 | [+8.44e-08, +1.24e-06] |
| SPY | 942 | 62,892 | -0.0672 | 1.836e-07 | 0.373 | [-7.52e-08, +4.97e-07] |

**VIX regime (VIXCLS at the prior observation, terciles)**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| high | 326 | 42,314 | -0.0066 | 3.826e-07 | 0.485 | [-4.15e-07, +1.35e-06] |
| low | 344 | 50,092 | -0.0077 | 4.108e-07 | 0.474 | [+2.47e-08, +9.90e-07] |
| middle | 335 | 50,536 | -0.0237 | 4.372e-07 | 0.430 | [+1.65e-08, +9.93e-07] |

### M(RV) vs B1 on set B

Exploratory (Research Plan section 5, Amendment 5): no claim in this section is confirmatory, and the intervals carry no multiplicity adjustment.

Reference: baseline. 1005 sessions, 142,942 observations; overall median rho -1.8900, mean d -1.692e-05, win rate 0.054.

**gap in days to the prior available session**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 376 | 62,737 | -2.0330 | -1.518e-05 | 0.074 | [-2.60e-05, -7.47e-06] |
| 2 | 295 | 29,448 | -1.7758 | -1.923e-05 | 0.031 | [-2.95e-05, -1.20e-05] |
| 3 | 248 | 40,989 | -1.9127 | -1.734e-05 | 0.044 | [-2.97e-05, -8.74e-06] |
| 4 | 45 | 6,156 | -1.4824 | -1.624e-05 | 0.067 | [-2.02e-05, -1.24e-05] |
| 5+ | 41 | 3,612 | -1.7322 | -1.437e-05 | 0.073 | [-1.64e-05, -1.23e-05] |

**maturity bucket (calendar days to expiry)**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| 31-90d | 950 | 74,700 | -2.2003 | -2.130e-05 | 0.049 | [-3.11e-05, -1.39e-05] |
| <=30d | 784 | 68,242 | -1.4022 | -1.117e-05 | 0.088 | [-1.64e-05, -6.93e-06] |
| >90d | 0 | 0 | n/a | n/a | n/a | none (fewer than 30 sessions) |

**moneyness tercile of |log(K/F)|**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| high | 1005 | 45,767 | -1.5330 | -1.452e-05 | 0.070 | [-2.44e-05, -7.38e-06] |
| low | 1005 | 49,060 | -2.5616 | -2.651e-05 | 0.060 | [-3.72e-05, -1.89e-05] |
| middle | 1005 | 48,115 | -1.1299 | -1.026e-05 | 0.093 | [-1.66e-05, -5.75e-06] |

**symbol**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| AAPL | 980 | 80,050 | -1.4759 | -1.944e-05 | 0.087 | [-2.99e-05, -1.12e-05] |
| SPY | 942 | 62,892 | -3.2504 | -1.235e-05 | 0.035 | [-1.50e-05, -1.01e-05] |

**VIX regime (VIXCLS at the prior observation, terciles)**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| high | 326 | 42,314 | -1.4391 | -2.940e-05 | 0.067 | [-4.70e-05, -1.56e-05] |
| low | 344 | 50,092 | -2.2911 | -9.893e-06 | 0.044 | [-1.20e-05, -7.96e-06] |
| middle | 335 | 50,536 | -1.9388 | -1.197e-05 | 0.051 | [-1.77e-05, -7.37e-06] |

### M(RV) vs RV baseline on set A

Exploratory (Research Plan section 5, Amendment 5): no claim in this section is confirmatory, and the intervals carry no multiplicity adjustment.

Reference: the model run's own baseline. 1056 sessions, 230,927 observations; overall median rho 0.1070, mean d 4.748e-04, win rate 0.646.

**gap in days to the prior available session**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 387 | 93,221 | 0.1125 | 2.112e-05 | 0.672 | [+5.21e-06, +4.41e-05] |
| 2 | 359 | 72,094 | 0.0962 | 8.709e-04 | 0.613 | [-2.08e-07, +2.61e-03] |
| 3 | 254 | 53,757 | 0.1070 | 7.095e-04 | 0.650 | [+3.88e-06, +2.11e-03] |
| 4 | 16 | 3,951 | 0.1225 | 2.141e-05 | 0.625 | none (fewer than 30 sessions) |
| 5+ | 40 | 7,904 | 0.1089 | 1.027e-06 | 0.675 | [-9.19e-07, +2.95e-06] |

**maturity bucket (calendar days to expiry)**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| 31-90d | 1056 | 103,116 | 0.1889 | 7.378e-04 | 0.760 | [+1.23e-05, +2.18e-03] |
| <=30d | 1056 | 127,811 | -0.0085 | 2.986e-04 | 0.493 | [+1.54e-06, +8.89e-04] |
| >90d | 0 | 0 | n/a | n/a | n/a | none (fewer than 30 sessions) |

**moneyness tercile of |log(K/F)|**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| high | 1056 | 76,976 | 0.1821 | 4.314e-04 | 0.641 | [-8.51e-06, +1.31e-03] |
| low | 1056 | 76,976 | -0.0208 | 5.243e-04 | 0.484 | [+9.59e-06, +1.53e-03] |
| middle | 1056 | 76,975 | 0.3735 | 4.842e-04 | 0.909 | [+1.23e-05, +1.42e-03] |

**symbol**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| AAPL | 1053 | 115,732 | 0.1408 | 8.685e-04 | 0.624 | [+6.74e-06, +2.58e-03] |
| SPY | 1042 | 115,195 | 0.0743 | 9.230e-06 | 0.584 | [+3.18e-06, +1.73e-05] |

**VIX regime (VIXCLS at the prior observation, terciles)**

| Cell | Sessions | Observations | Median rho | Mean d | Win rate | 95% interval for mean d |
|---|---:|---:|---:|---:|---:|---:|
| high | 352 | 76,925 | 0.1906 | 1.403e-03 | 0.693 | [+7.00e-06, +4.21e-03] |
| low | 352 | 75,571 | 0.0375 | 2.109e-06 | 0.574 | [-1.15e-07, +4.53e-06] |
| middle | 352 | 78,431 | 0.1381 | 1.959e-05 | 0.670 | [+2.67e-06, +4.47e-05] |

