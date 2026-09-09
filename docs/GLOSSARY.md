# Glossary

- L_base,t and L_model,t: session t mean squared spot-normalized pricing error for the baseline and the model. The series behind every test.
- d_t = L_base,t - L_model,t: loss differential, MSE units. Positive means the model won that session.
- rho_t = 1 - sqrt(L_model,t) / sqrt(L_base,t): relative improvement in RMSE terms. The v1 per-fold improvement column.
- Delta_k: median over sessions of rho under configuration k.
- S_k = Delta_k / Delta_0: fraction of the v1 improvement surviving carry correction k. S_3 is the primary estimand.
- C0 to C3: the 2 x 2 carry configurations (constant or historical rate, constant or historical dividend).
- Set A: observations passing the v1 quality gates that price without error under all four configurations. Frozen once, reused by every Design A run.
- iv_not_identified: the mid lies outside the no-arbitrage bounds under a configuration, so no implied volatility exists. The only set A drop reason.
- Support guard: v1 rule that reverts a session to the baseline when a feature value lies outside the training window's range plus a 10% margin. r and q are excluded from it in Design A (Amendment 3); the v1 form is a sensitivity.
- Prior available session: the previous session present in the store, not the previous calendar session; the source lacks 664 of 1,841 sessions.
- B1, B2: prior-session implied volatility and prior-session SVI baselines (Design B).
- DM (HLN): Diebold-Mariano with the Harvey-Leybourne-Newbold correction. Newey-West: HAC t-statistic with lags floor(1.5 * n^(1/3)). Neither decides anything; the circular block bootstrap does.
