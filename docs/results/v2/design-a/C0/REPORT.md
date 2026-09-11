# Walk-forward evaluation

1056 folds, one held-out session each, from 2020-10-23 to 2026-09-04. Window: rolling, embargo gap: 1 session(s).

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.664 |
| Mean loss differential (baseline - model) | 4.732e-04 |
| Diebold-Mariano statistic (HLN) | 3.672 |
| Two-sided p-value | 0.0002523 |
| DM with Newey-West HAC (15 lags) | 1.224 (p = 0.2211) |
| Lag-1 autocorrelation of the differential | 0.874 |
| Bootstrap 95% CI for the differential | [9.980e-06, 1.249e-03] |
| CI excludes zero | True |

Losses are session means of squared spot-normalized pricing errors against
contemporaneous midpoints. A positive differential favors the learned model.
This measures pricing accuracy on later sessions under the maintained
assumptions; it is not a forecast of option returns and not a tradable claim.
Session-level aggregation and the block bootstrap address serial dependence,
but overlapping contract lives still link adjacent sessions.
