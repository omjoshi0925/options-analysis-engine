# Talk outline (12 minutes), drafted 2026-09-09

1. Question (1 min). A learned adjustment beat a flat realized-vol baseline on SPY and AAPL, median 10.4% per fold across 1,056 sessions. Both priced under a constant 4% rate through a period when 3-month Treasuries went from near zero to above 5%. Structure, or compensation?
2. The v1 result and its caveat (2 min). Positive every year; naive DM significant, Newey-West not, block bootstrap excludes zero. Why serial dependence (lag-1 autocorrelation 0.87) makes the naive test wrong.
3. Design A (2 min). 2 x 2 carry factorial on one frozen observation set, identical folds, decision rule fixed before the runs. S_k defined.
4. What survives (3 min). S_1, S_2, S_3 with intervals: [fill from docs/results/v2/design-a/comparison.json]. Carry-only check: [fill]. Decision label: [fill]. Guard sensitivity agreement: [fill].
5. Stronger baselines (2 min, if Design B is done). Prior-session IV and SVI: does the model add anything beyond yesterday's smile? [fill]
6. Limitations (1 min). Two symbols; source missing 36% of sessions; EOD only; continuous-yield dividend approximation; the mids that violate no-arbitrage bounds under near-zero rates.
7. Reproducibility (1 min). Tag, manifest, one command to verify, pre-registered plan with amendments.

Backup slides: observation-set drop breakdown; per-year ratio-of-means versus per-fold median; the 21 rate-jump sessions.
