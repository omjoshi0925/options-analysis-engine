# Research notebook

Dated working notes on the empirical record, in chronological order. Each
entry says what was done, what it rests on, and what could not be established.

## 2026-09-08: freezing the v1 study (tag `study-v1`)

**Scope.** Freeze the study reported in `docs/RESULTS.md` so that every
number there traces to a saved output. Code is `options_engine` 3.2.1 at
commit 5339396, the commit that added the report. No model code changed, no
walk-forward was rerun, and no number in the report was edited.

**What was frozen.** The 1,056-fold full-history walk-forward
(`results/full-history-v2`: folds.csv, significance.json, REPORT.md), the
83-fold SPY 2023 run (`results/spy-2023-v2`), the earlier full-history-v1 fold
table (its report and significance file were already committed), and the
observation exports with exclusion reasons for both data roots. All of it now
lives under `docs/results/`; the two exports exceed 10 MB uncompressed
(349.7 MB and 20.4 MB) and are committed gzipped, with the uncompressed hash
recorded. The import CSVs, the two observation stores, and the 1,321 snapshot
directories stay local: their SHA-256 hashes are in the manifest, and the raw
DoltHub exports are not redistributed pending the license check the report
already calls for.

**How the tracing was done.** `docs/results/build_manifest.py` hashes every
artifact (import CSVs, snapshot metadata and raw files, stores, run outputs,
exports, configs, the DoltHub clone heads) and writes `manifest.json` with 157
claims: each numeric statement in the report, its source file, the field or
derivation that produces it, and the value. Running the script with `--check`
recomputes everything from the committed artifacts (and the local-only sources
when present) and passed. Status counts: 73 read directly from a saved field,
77 derived by a stated computation from a saved file, 3 read from code
constants, 2 verified by a recorded run (`docs/results/verification-3.2.1.txt`
holds the pytest and ruff output: 181 passed, lint clean), 2 untraceable.

**Traced directly.** Import totals (292,018 quotes, 1,177 sessions, 260,296
training-eligible), every row of the exclusion table, the full-history and
SPY 2023 win rates, mean differentials, Diebold-Mariano and Newey-West
statistics and p-values, lag-1 autocorrelation, the block-10 and block-4
bootstrap intervals, the walk-forward specifications, and the rate, dividend,
and window parameters.

**Derived, not present in any output the study saved.** The bootstrap
intervals at block lengths 21, 63, and 126 were computed in an unsaved session;
re-deriving them from folds.csv with the package's own function (seed 0, 2,000
replications) reproduces every bound to the reported precision except the
block-63 lower bound, which renders as 5.04e-06, not 5.05e-06. They are saved
in `docs/results/full-history-v2/bootstrap-block-lengths.json`. The median and
interquartile per-fold improvement, the mean session RMSEs, and the per-year
table are computed from folds.csv (the per-year improvement is one minus the
ratio of mean RMSEs; the mean of per-fold improvements is negative in 2021 and
2023, so the "positive in every year" statement depends on that definition).
The refusal counts come from the import summary, which was printed and not
saved; they were recomputed from `full_chain.csv` with the XNYS calendar.

**Could not be traced, or disagrees with the saved outputs. Left unchanged.**

- "54 exchange holidays carrying stale rows": the export has 55 weekday
  holidays plus one Saturday (2020-01-04) outside 2019, so the refused dates
  are 47 + 55 + 1 = 103.
- "2 sessions where the SPY underlying close was missing" are real events,
  recorded in the metadata of the 2022-08-01 and 2022-09-19 snapshots, but
  those sessions were accepted with AAPL rows; they are not among the 103
  refused sessions.
- "SPY, QQQ, AAPL": the cloned `option_chain` table holds no QQQ rows, so the
  store, the folds, and every figure cover SPY and AAPL only.
- The report says the export files' hashes are recorded in every snapshot's
  metadata. Both imports ran before the 3.2.1 change that does this, so the
  snapshot metadata has no `source_files` entry; the hashes are in the
  manifest instead. Each snapshot's own raw_options.csv hash is in its
  metadata, and all 1,321 match.
- Block-63 lower bound 5.05e-06 (see above).

**Generated during the freeze.** The full-history exclusion export did not
exist; it was produced with `export --config config/eod-full.json
--include-excluded`, and the store's hash was identical before and after. The
SPY 2023 export existed; a fresh export was byte-identical to it. A "Data
coverage vs evaluation window" section was added to the report above
Limitations, with every figure read from the saved artifacts and listed in the
manifest: 1,280 raw dates of which 103 are non-sessions, 664 of 1,841 calendar
sessions absent from the source (roughly every other session through 2024),
236,516 evaluated quotes over 1,056 sessions, per-symbol counts, and the SPY
2023 subsample.

**Open questions for a v2 study.** A time-varying risk-free rate and an SVI
competitor (already listed in the report); whether the source ever carries QQQ
option rows; how the alternate-day gaps in 2020 to 2024 affect the serial
dependence adjustments, which are counted in stored sessions rather than
calendar days; and the source license before any export is redistributed.

## 2026-09-08 (later): correcting the flagged claims in RESULTS.md

Applied the corrections the freeze flagged, using manifest values verbatim
and recomputing nothing. The tag `study-v1` was left at b41237d, so the
manifest's `report_sha256` still describes the tagged report; the manifest
was not edited. `build_manifest.py --check` after the edits: all 157 claims
and all 13 committed artifact hashes pass, and the only reported problem is
that `docs/RESULTS.md` differs from the frozen report hash, which is exactly
this change.

- Symbols: "SPY, QQQ, AAPL" is now "SPY and AAPL" in the Summary and in the
  dividend-yield sentence (the configured 0.6% QQQ yield was never used); the
  Data section states that QQQ was requested and that the source
  `option_chain` table contains zero QQQ rows.
- Refusals: "54 exchange holidays" replaced by the manifest breakdown, 47
  weekend-stamped 2019 dates, 55 weekday exchange holidays, and 1 Saturday
  (2020-01-04), 103 refused dates in total carrying 22,282 rows.
- Missing SPY close: 2022-08-01 and 2022-09-19 are now described as sessions
  accepted with AAPL rows only, with the 284 SPY rows dropped, not as
  refusals.
- Block-63 lower bound: 5.05e-06 corrected to 5.04e-06.
- Provenance: the Data and Reproducibility sections now say the export file
  hashes are recorded in `docs/results/manifest.json`, not in snapshot
  `metadata.json`, because both imports predate the 3.2.1 hashing change; the
  claim that export queries are recorded was dropped, since nothing records
  them. The Reproducibility section names
  `docs/results/full-history-v2/bootstrap-block-lengths.json` as the saved
  source of the block-length table.
