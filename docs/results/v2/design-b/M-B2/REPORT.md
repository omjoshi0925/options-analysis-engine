# Walk-forward evaluation

1005 folds, one held-out session each, from 2020-11-16 to 2026-09-04. Window: rolling, embargo gap: 1 session(s).

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.241 |
| Mean loss differential (baseline - model) | -4.825e-06 |
| Diebold-Mariano statistic (HLN) | -6.818 |
| Two-sided p-value | 1.587e-11 |
| DM with Newey-West HAC (15 lags) | -3.542 (p = 0.0004151) |
| Lag-1 autocorrelation of the differential | 0.263 |
| Bootstrap 95% CI for the differential | [-7.624e-06, -2.856e-06] |
| CI excludes zero | True |

Losses are session means of squared spot-normalized pricing errors against
contemporaneous midpoints. A positive differential favors the learned model.
This measures pricing accuracy on later sessions under the maintained
assumptions; it is not a forecast of option returns and not a tradable claim.
Session-level aggregation and the block bootstrap address serial dependence,
but overlapping contract lives still link adjacent sessions.
