# Walk-forward evaluation

1004 folds, one held-out session each, from 2020-11-16 to 2026-09-04. Window: rolling, embargo gap: 1 session(s).

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.497 |
| Mean loss differential (baseline - model) | 5.250e-07 |
| Diebold-Mariano statistic (HLN) | 2.887 |
| Two-sided p-value | 0.003969 |
| DM with Newey-West HAC (15 lags) | 2.262 (p = 0.02394) |
| Lag-1 autocorrelation of the differential | 0.032 |
| Bootstrap 95% CI for the differential | [1.088e-07, 9.673e-07] |
| CI excludes zero | True |

Losses are session means of squared spot-normalized pricing errors against
contemporaneous midpoints. A positive differential favors the learned model.
This measures pricing accuracy on later sessions under the maintained
assumptions; it is not a forecast of option returns and not a tradable claim.
Session-level aggregation and the block bootstrap address serial dependence,
but overlapping contract lives still link adjacent sessions.
