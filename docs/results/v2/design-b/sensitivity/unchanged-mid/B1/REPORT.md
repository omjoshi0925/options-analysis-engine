# Walk-forward evaluation

379 folds, one held-out session each, from 2020-11-23 to 2026-09-04. Window: rolling, embargo gap: 1 session(s).

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.000 |
| Mean loss differential (baseline - model) | 0.000e+00 |
| Diebold-Mariano statistic (HLN) | degenerate |
| Two-sided p-value | degenerate |
| DM with Newey-West HAC (10 lags) | degenerate (p = degenerate) |
| Lag-1 autocorrelation of the differential | 0.000 |
| Bootstrap 95% CI for the differential | [0.000e+00, 0.000e+00] |
| CI excludes zero | False |

Losses are session means of squared spot-normalized pricing errors against
contemporaneous midpoints. A positive differential favors the learned model.
This measures pricing accuracy on later sessions under the maintained
assumptions; it is not a forecast of option returns and not a tradable claim.
Session-level aggregation and the block bootstrap address serial dependence,
but overlapping contract lives still link adjacent sessions.
