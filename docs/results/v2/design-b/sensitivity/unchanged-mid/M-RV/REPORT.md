# Walk-forward evaluation

379 folds, one held-out session each, from 2020-11-23 to 2026-09-04. Window: rolling, embargo gap: 1 session(s).

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.533 |
| Mean loss differential (baseline - model) | 7.954e-05 |
| Diebold-Mariano statistic (HLN) | 1.502 |
| Two-sided p-value | 0.1338 |
| DM with Newey-West HAC (10 lags) | 1.461 (p = 0.1449) |
| Lag-1 autocorrelation of the differential | 0.012 |
| Bootstrap 95% CI for the differential | [9.266e-06, 2.056e-04] |
| CI excludes zero | True |

Losses are session means of squared spot-normalized pricing errors against
contemporaneous midpoints. A positive differential favors the learned model.
This measures pricing accuracy on later sessions under the maintained
assumptions; it is not a forecast of option returns and not a tradable claim.
Session-level aggregation and the block bootstrap address serial dependence,
but overlapping contract lives still link adjacent sessions.
