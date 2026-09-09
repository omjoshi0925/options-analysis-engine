# docs/results

- manifest.json: every numeric claim in docs/RESULTS.md mapped to its source file and field, plus SHA-256 for every artifact and config. Rebuild with build_manifest.py; verify with `--check`.
- verification-3.2.1.txt: test and lint output recorded at the freeze.
- full-history-v1/, full-history-v2/: fold-level outputs of the 1,056-session walk-forward (folds.csv), bootstrap intervals by block length, and the observation export with exclusion reasons (gzipped; hash of the uncompressed file is in the manifest).
- spy-2023-v2/: the 83-fold SPY 2023 subsample with its significance JSON and report.
- v2/: study v2 artifacts per docs/RESEARCH_PLAN.md. observation-set-A.csv is the frozen Design A set; design-a/C0 to C3 hold the carry-robustness runs; comparison.json and REPORT.md hold S_k and the decision label.

folds.csv is one row per evaluated session. Losses are session mean squared spot-normalized pricing error for baseline and model; RMSE columns are their square roots; rho is the relative improvement in RMSE terms; d is the loss differential in MSE terms. Effective r and q per session are recorded from v3.3 onward. Definitions are in docs/GLOSSARY.md.
