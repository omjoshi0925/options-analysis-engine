# Walk-forward evaluation

1056 folds, one held-out session each, from 2020-10-23 to 2026-09-04. Window: rolling, embargo gap: 1 session(s).

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.646 |
| Mean loss differential (baseline - model) | 4.748e-04 |
| Diebold-Mariano statistic (HLN) | 3.662 |
| Two-sided p-value | 0.0002625 |
| DM with Newey-West HAC (15 lags) | 1.221 (p = 0.2224) |
| Lag-1 autocorrelation of the differential | 0.875 |
| Bootstrap 95% CI for the differential | [8.874e-06, 1.255e-03] |
| CI excludes zero | True |

Losses are session means of squared spot-normalized pricing errors against
contemporaneous midpoints. A positive differential favors the learned model.
This measures pricing accuracy on later sessions under the maintained
assumptions; it is not a forecast of option returns and not a tradable claim.
Session-level aggregation and the block bootstrap address serial dependence,
but overlapping contract lives still link adjacent sessions.
