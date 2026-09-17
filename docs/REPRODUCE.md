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

## Repository size

The repository is about 200 MB because the committed observation exports under docs/results/ are the study's evidence: their SHA-256 hashes are what `build_manifest.py --check` verifies, and the counts in docs/RESULTS.md are computed from them. A reproducer who only needs to verify the frozen study does not need the history:

    git clone --depth 1 --branch study-v1 --no-tags https://github.com/omjoshi0925/options-analysis-engine

downloads about 110 MB (105 MiB packed, measured 2026-09-15) and still supports `python docs/results/build_manifest.py --check` on the v1 artifacts; the claims whose source is a local-only file are reported as skipped, not as failures. Without `--no-tags` git also fetches the tree behind the study-v2-locked tag and the download is about 200 MB. The full history is needed only to inspect earlier runs and the study v2 artifacts.

History is never rewritten. Tag and commit hashes are cited in docs/LOCK.md, in the amendments of docs/RESEARCH_PLAN.md, and in CITATION.cff; a rewrite would move the tags and falsify every one of those citations.

## Fresh evaluation (Design D)

`scripts/fresh_session.sh` runs each weekday morning, after the DoltHub source has published the previous session. It pulls the option source and looks for a session dated after the lock that is not yet scored; with none it exits quietly. Otherwise it refreshes the inputs that need no chain, runs `predict-locked`, commits the prediction files, and only then exports that session's chain, imports it, runs `score-locked`, appends the docs/FRESH_EVAL.md line, rebuilds the manifest, and pushes. `--dry-run` reports what would run. Any refusal from the locked commands stops the run and is printed. The per-run retrieval record is the last table of data/external/PROVENANCE.md; each prediction sidecar carries the hashes of the inputs it used.

