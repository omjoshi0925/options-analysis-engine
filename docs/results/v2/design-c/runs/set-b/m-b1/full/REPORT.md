# Walk-forward evaluation

1005 folds, one held-out session each, from 2020-11-16 to 2026-09-04. Window: rolling, embargo gap: 1 session(s).

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.463 |
| Mean loss differential (baseline - model) | 4.104e-07 |
| Diebold-Mariano statistic (HLN) | 2.757 |
| Two-sided p-value | 0.005943 |
| DM with Newey-West HAC (15 lags) | 2.180 (p = 0.02946) |
| Lag-1 autocorrelation of the differential | 0.024 |
| Bootstrap 95% CI for the differential | [8.527e-08, 7.713e-07] |
| CI excludes zero | True |

Losses are session means of squared spot-normalized pricing errors against
contemporaneous midpoints. A positive differential favors the learned model.
This measures pricing accuracy on later sessions under the maintained
assumptions; it is not a forecast of option returns and not a tradable claim.
Session-level aggregation and the block bootstrap address serial dependence,
but overlapping contract lives still link adjacent sessions.
