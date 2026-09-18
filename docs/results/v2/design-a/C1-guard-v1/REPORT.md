# Walk-forward evaluation

1056 folds, one held-out session each, from 2020-10-23 to 2026-09-04. Window: rolling, embargo gap: 1 session(s).

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.635 |
| Mean loss differential (baseline - model) | 4.752e-04 |
| Diebold-Mariano statistic (HLN) | 3.665 |
| Two-sided p-value | 0.00026 |
| DM with Newey-West HAC (15 lags) | 1.222 (p = 0.222) |
| Lag-1 autocorrelation of the differential | 0.874 |
| Bootstrap 95% CI for the differential | [9.231e-06, 1.256e-03] |
| CI excludes zero | True |

Losses are session means of squared spot-normalized pricing errors against
contemporaneous midpoints. A positive differential favors the learned model.
This measures pricing accuracy on later sessions under the maintained
assumptions; it is not a forecast of option returns and not a tradable claim.
Session-level aggregation and the block bootstrap address serial dependence,
but overlapping contract lives still link adjacent sessions.
