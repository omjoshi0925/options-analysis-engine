# Reproducing the study-v1 numbers from a clean install

Target: every number in docs/RESULTS.md, each traced by docs/results/manifest.json at tag study-v1 (b41237d).

1. Environment: Python 3.11 or newer, git, dolt.
   git clone https://github.com/omjoshi0925/options-analysis-engine && cd options-analysis-engine
   git checkout study-v1
   python -m venv .venv && source .venv/bin/activate && pip install -e . pytest ruff
2. Verify the committed artifacts before running anything:
   python docs/results/build_manifest.py --check
   This confirms every fold-level output and export on disk matches its recorded hash. If it passes, the reported numbers are traceable without a rerun.
3. Optional full rerun (about 7 minutes for the walk-forward, plus export time): the exact dolt export, import, and walk-forward invocations are in docs/RESULTS.md under Reproducibility. Run them in order into a fresh results directory, then diff its folds.csv against docs/results/full-history-v2/folds.csv.
4. Expected differences: none in fold dates, win rate, or the DM statistic if the DoltHub source matches the clone date in docs/RESULTS.md (2026-09-08). A newer clone adds sessions after 2026-09-07 and changes every count.
5. Report the outcome with the "Reproduction report" issue template, including which manifest claims matched and which did not.
