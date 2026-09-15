# Study v2 lock (Design D)

Locked on 2026-09-15 per docs/RESEARCH_PLAN.md section 7 and Amendment 7. From this point no model, feature, hyperparameter, configuration, or analysis change is made. The locked commands verify the hashes in docs/lock.json before running and refuse if any locked file differs, so the lock is enforced by the code, not only by this document.

## Locked commit and version

- Code commit: `f3e85ec8dca2de36abbb8c30fdbfc0d32a6f015e`, `options_engine` 3.6.0. The tag `study-v2-locked` points at the commit that adds this document, docs/lock.json, and the rebuilt manifest on top of it; every hashed file is identical at both commits.
- Lock date: 2026-09-15. Fresh sessions are those dated strictly after it. The store's last session at the lock is 2026-09-04; sessions between that date and the lock date, if ever imported, are history only and are never scored.
- Chosen model and configuration: the v1 ridge adjustment M(RV) (features, target, alpha grid {0.01, 1, 100}, support guard as amended by Amendment 3) under config/v2/C3.json (dated carry: FRED DGS3MO strictly prior, trailing-365-day distribution yield), evaluated alongside B1 and M(B1) (Amendment 4) and the RV baseline. All four are priced on every fresh session (Amendment 7).
- Fold rule for a fresh session t: a rolling window of the 250 stored sessions before the prior available session (gap 1), 120-session minimum, alpha reselected on the last two training sessions and the model refit on the window; identical to the pre-registered walk-forward and recorded as `spec` in docs/lock.json.

## Hashes (SHA-256)

Every file below is verified by `predict-locked` and `score-locked` against docs/lock.json.

| File | SHA-256 |
|---|---|
| config/eod-full.json | `34efc9fa9e2aecf414fac04686fb320934cef0ef51200241b5079e181cf1100d` |
| config/v2/C3.json | `061e3f05847d84db807d67b905a5fa5d7a7b8756f8a043e73045bfc1cdba2348` |
| options_engine/analysis.py | `936c31d3ba5740e4e8ecde549d39daf84e6e44165b1fa9d7a048c340b06fffc0` |
| options_engine/baselines.py | `3224e01c48f6cfc4f5ea09c71aacabdbb7058a0f018c708a7d1f0e6c55ba414d` |
| options_engine/carry_inputs.py | `642656c19f2e0afb9e94808ec7502ff67ef3efd65bf5047bcdcc82a2facbd504` |
| options_engine/compare.py | `5e5bd5a2c1fd379948986a93b7c6148ad65e6f44c2bc09b70f26079423c2650a` |
| options_engine/core.py | `9a80208e1ca5d12b7c52a4c0f15ac0ef79605bfbbecc70dd44a473ab06d4245d` |
| options_engine/data.py | `2eaf9bc6e397b61a295f0b84bd45e19db964a54ce462678aa69d91db70fff3ec` |
| options_engine/eod_import.py | `fca9097773865695a08713562fae23208940f3c15bae0a879f0477262c3ece28` |
| options_engine/iv.py | `fefac0e5ec89d5a7865362d089dc17f11c25ce001d1a8cc30d55c050220ab094` |
| options_engine/learning.py | `21118f3aab2a83b34112319fc574266390b9d32dc83ed224b113dfd52a9620ac` |
| options_engine/live_config.py | `39817fc78cfadea26eca975bcd23ecb5224a9128225c64f78eb06caa56891106` |
| options_engine/locked.py | `4399723df7d931ffca7b00887a1dbb7d452557cecb431c1bfdaa64118c29de9d` |
| options_engine/store.py | `9b59289a6cb9777e90bc0de6291efcfdff8a4a4c714a752780c5fd8546c5165d` |
| options_engine/volatility.py | `7baea2216fb1e8d8556c77dd6c7a4b5f27c9113073354dfa2907a07df56c8a45` |
| options_engine/walkforward.py | `1399ffa4e0c7e77300df90f55a5d19b4b2e41d102b5b00d9c893f509dae59092` |

Files recorded for reference, not enforced (glue and exploratory code):

| File | SHA-256 |
|---|---|
| options_engine/cli.py | `07b9dcc5d28c4e6360bd28f7a42ac89fc01d9997ad40b4201edfebad3b0bd625` |
| options_engine/attribution.py | `75020b5089b7f80c585526522a3e1afcd9f8a761d30af275f5ab03218f619652` |
| options_engine/stale_quotes.py | `28bb82f284ee53e342bd07a910fa1c0bc6056d8b69274182e797112571752893` |
| options_engine/observation_set.py | `d3910a95a0264ab1e53c8b548ab4f7c7d315dc41e6de73ec2eb2c1dd3209e8f3` |
| options_engine/live_utils.py | `234f5d24d9b08b68a489e09fd835264fc5af9bc572d9021b17608727e8f5b985` |
| options_engine/american.py | `b2e9134b67723226e1a57897bbe3d505a941742d7e96a373e60f13dc3857020d` |
| scripts/build_external_inputs.py | `c45e9b53c4bb0ef2edc98394d7fb23c43b720874453a900815f934168be47246` |
| docs/results/build_manifest.py | `0cbd4b050b1943d77c376fedce26ddf0a50be16e8ad53809a5a42690e68cb947` |

Data inputs at the lock. The rate, bar, and distribution files are refreshed per fresh session; each refresh is hashed in that session's prediction sidecar.

| File | SHA-256 |
|---|---|
| data/external/raw/DGS3MO.csv | `504030af381b2ee828c3012ba91dcc9ea7cdbbcaa3297026acd500ed9c4b4e44` |
| data/external/raw/VIXCLS.csv | `60f2ec1ea081cf27427b8a24930a2ebee7c1992aad14119e9380673cc85fb9c1` |
| data/external/raw/full_underlying.csv | `aa9e446dddf40682a68890a0b70f36a41c6d2f108d0777dddc1b7403801bc738` |
| data/external/dividends.csv | `7cc323daac11272eee3949729e7ee435ae865670ccb76b3424f80068cdbf39d2` |
| data/external/splits.csv | `96053ba693b69c0e192622dadfd9dcb48db42d1829855334a067c69b17fb9fec` |
| docs/results/v2/observation-set-A.csv.gz | `81234b995f154331a190c9e0e126308b386d217957dcb99e3c5f228404f846df` |
| docs/results/v2/observation-set-B.csv.gz | `12a371b4837d190c5eb43314304863de49edfb25004845180681a3dcef5d5051` |
| docs/results/v2/baselines-B.csv.gz | `d4f886aaefbd202f86d03b065dbdc76e7915a3f9aa72bb3d545b3c4f64bcd99e` |
| docs/results/v2/design-b/comparison.json | `537b3c357887e6d1696480d606639e9d6dd854add4bd7625838b4e2614ee2994` |
| docs/results/v2/design-c/breakdowns.json | `653daff234824a97b9847f43594d44ee557dbe6a65357d45a7b3e4fd59bb6def` |

## Invocations

Per fresh session t (dates as YYYY-MM-DD), in this order with nothing in between:

```bash
# 1. Inputs without the chain: bars through t from the stocks database, the rate, the distribution histories.
curl -sS -o data/external/raw/DGS3MO.csv "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO"
(cd stocks && dolt pull && dolt sql -r csv -q "SELECT date, act_symbol, open, high, low, close FROM ohlcv WHERE act_symbol IN ('SPY','AAPL')") > data/external/raw/full_underlying.csv
python scripts/build_external_inputs.py          # after refreshing the raw issuer files as data/external/PROVENANCE.md describes
# 2. Predict, then commit the prediction file before the chain is touched.
python -m options_engine predict-locked --session t --config config/v2/C3.json \
  --underlying-csv data/external/raw/full_underlying.csv --dividend-history-end <retrieval date of the distribution histories> \
  --out-dir docs/results/v2/fresh
git add docs/results/v2/fresh/predictions-t.csv docs/results/v2/fresh/predictions-t.json data/external
git commit -m "fresh: predictions for t"
# 3. Only now export and import the option chain for t.
(cd options && dolt pull && dolt sql -r csv -q "SELECT date, act_symbol, expiration, strike, call_put, bid, ask, vol FROM option_chain WHERE act_symbol IN ('SPY','AAPL') AND date = 't'") > fresh_chain_t.csv
python -m options_engine import-eod --config config/eod-full.json --chain-csv fresh_chain_t.csv --underlying-csv data/external/raw/full_underlying.csv
# 4. Score and commit.
python -m options_engine score-locked --session t --config config/v2/C3.json --predictions-dir docs/results/v2/fresh --log docs/FRESH_EVAL.md
git add docs/results/v2/fresh/scores-t.json docs/FRESH_EVAL.md
git commit -m "fresh: scores for t"
```

`predict-locked` refuses when the chain for t is already in the store (any observation or snapshot dated t), when the store holds a session after t, when t is not an XNYS session or not after the lock date, when the prediction files exist, and when any locked file differs from docs/lock.json. `score-locked` refuses when the prediction file is not committed, differs from HEAD, or differs from the hash in its sidecar; when the chain for t is not in the store; and when the chain's import run started before the prediction commit. Inference, `python -m options_engine fresh-eval-report --scores-dir docs/results/v2/fresh --out docs/results/v2/fresh/report --vix data/external/raw/VIXCLS.csv`, refuses until the sample rule is met.

## Sample rule

The first 60 available sessions after the lock date, or all sessions available by 2027-03-31, whichever comes first, with no interim stopping based on results. "Available" means present in the DoltHub source; the source's gaps are recorded per session as the gap in days to the prior available session. Inference follows section 6 (paired circular block bootstrap over sessions, block 21, 10,000 replicates, seed 20260908, sensitivity at 10, 63, and 126 where the sample allows them; Diebold-Mariano and Newey-West reported for continuity, not for decisions) and is reported at whatever width the sample supports, against the Amendment 7 expectations. Nothing is computed from the accumulating losses before the rule is met; docs/FRESH_EVAL.md only logs each session's counts and losses.

## Per-session protocol

1. Import the underlying close S_t from the stocks database only (bars through t). Refresh the rate and distribution files. The option chain for t is not exported and not read.
2. Form the prediction set: every contract among the store's training-eligible rows at the prior available session t-1 that prices under C3 (the rows the walk-forward trains on, at most 500 per symbol and session) whose expiry lies after t's close. Price each under the RV baseline (60 close-to-close returns of the bars strictly before t), B1 (the contract's own implied volatility at t-1, solved under t-1's carry, re-priced at t), and M(RV) and M(B1) (fitted by the fold rule above from stored sessions only), all with S_t, r_t, q_t and time to expiry measured from t's close. Write predictions-t.csv, with the UTC timestamp on every row, and predictions-t.json with the file's SHA-256, the input hashes, the training windows, and the counts. Commit both.
3. Only then export and import the option chain for t. `score-locked` verifies the commit, matches on the contract key (symbol, contractSymbol), scores the predicted contracts that appear at t and pass the v1 quality gates and the identification rule the pre-registered evaluation applied (implied volatility identified under the locked carry and within [0.03, 3]), records every unscored predicted contract by reason (absent at t; quality-excluded at t, with reasons; not identified), ignores contracts at t that were not predicted (counted, never scored), and appends one line to docs/FRESH_EVAL.md. The session's four losses are means over the scored contracts of the squared spot-normalized pricing error against t's mids.

The separation between inputs and targets is physical: the chain file for t is not read until the prediction commit exists, and `score-locked` refuses a chain imported before that commit.

## Operational interpretations of section 7

- Training universe for fresh sessions: the store's training-eligible rows that price under C3, the walk-forward's own rule without an observation set. Over the study span this coincides with set A except for rows that fail identification only under C0 to C2: set A dropped 6,742 rows that failed under any configuration, of which 6,279 fail under C3 itself, so the locked training windows differ from the pre-registered ones by at most 463 rows over 1,177 sessions.
- Scoring universe: every predicted contract present at t, not the 500-per-symbol sample the walk-forward drew for evaluation; no contract is excluded on the basis of its loss.
- Refreshed inputs: the configuration file is never edited. The per-session rate, bar, and distribution files replace the configuration's paths at run time and are hashed in the sidecar; `--dividend-history-end` states the retrieval date of the refreshed distribution history so the declared-coverage guard of Amendment 3 applies to it.
- The RV baseline for t uses the bars strictly before t, exactly as the import stamps it on stored sessions; S_t enters pricing only.
- Out-of-symbol transfer (section 7, secondary): not pre-specified here, because the source holds no symbol untouched by development work.
