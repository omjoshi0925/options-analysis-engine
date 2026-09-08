# Walk-forward evaluation

1056 folds, one held-out session each, from 2020-10-23 to 2026-09-04. Window: rolling, embargo gap: 1 session(s).

| Quantity | Value |
|---|---:|
| Model win rate (session loss) | 0.664 |
| Mean loss differential (baseline - model) | 4.495e-04 |
| Diebold-Mariano statistic (HLN) | 3.671 |
| Two-sided p-value | 0.0002538 |
| Bootstrap 95% CI for the differential | [1.003e-05, 1.187e-03] |
| CI excludes zero | True |

Losses are session means of squared spot-normalized pricing errors against
contemporaneous midpoints. A positive differential favors the learned model.
This measures pricing accuracy on later sessions under the maintained
assumptions; it is not a forecast of option returns and not a tradable claim.
Session-level aggregation and the block bootstrap address serial dependence,
but overlapping contract lives still link adjacent sessions.
