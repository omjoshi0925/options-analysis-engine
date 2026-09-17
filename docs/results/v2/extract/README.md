# Reviewer extract (inspection only)

For people and agents that cannot open the full exports. No reported number comes from this sample; every reported number traces to the
files listed in docs/results/manifest.json.

- observations-sample.csv: 38,545 evaluated observations (15,281,948 bytes uncompressed), a deterministic stratified sample of set A evaluated observations (docs/results/v2/design-c/runs/set-a/full/predictions.csv.gz), which contain every set B evaluated observation.
  Strata: symbol x year x option type x maturity bucket (30 days or fewer, more than 30 days); at most 700 rows per stratum (56 strata), drawn without replacement with numpy default_rng seed 20260908 by row order
  within the stratum. Columns carry the RV baseline and M(RV) sigma and price for every row, the B1 and M(B1) sigma and price for the
  22,237 rows that are also in set B, the quote's European implied volatility, the early-exercise premium on a 200-step CRR tree
  as a fraction of the mid, and the quote tick (Amendment 8 diagnostic).
- folds/: verbatim copies of every fold table under docs/results/ (29 files), named by their source directory.
- extract.json: the sampling rule, per-stratum counts, and the SHA-256 of every file here.
