# Walk-forward evaluation

83 folds, one held-out session each, from 2023-06-12 to 2023-12-29. Window: expanding, embargo gap: 1 session(s).

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.687 |
| Mean loss differential (baseline - model) | 3.369e-06 |
| Diebold-Mariano statistic (HLN) | 4.863 |
| Two-sided p-value | 5.506e-06 |
| DM with Newey-West HAC (6 lags) | 2.086 (p = 0.04011) |
| Lag-1 autocorrelation of the differential | 0.882 |
| Bootstrap 95% CI for the differential | [8.397e-07, 5.984e-06] |
| CI excludes zero | True |

Losses are session means of squared spot-normalized pricing errors against
contemporaneous midpoints. A positive differential favors the learned model.
This measures pricing accuracy on later sessions under the maintained
assumptions; it is not a forecast of option returns and not a tradable claim.
Session-level aggregation and the block bootstrap address serial dependence,
but overlapping contract lives still link adjacent sessions.
