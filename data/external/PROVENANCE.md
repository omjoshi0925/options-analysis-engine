# External inputs: provenance

Retrieved on 2026-09-09 (UTC) for study v2, Design A (docs/RESEARCH_PLAN.md
section 2). Every file under data/external/ is committed; the SHA-256 values
below are repeated in docs/results/manifest.json. Nothing here was typed from
memory: every number in dividends.csv and splits.csv is parsed from a raw
file by scripts/build_external_inputs.py.

## 1. Risk-free rate: FRED DGS3MO

- File: raw/DGS3MO.csv
- URL: https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO
- Retrieved: 2026-09-09T03:48:03Z with curl 8.7.1 (default User-Agent).
  Requests that imitated a browser User-Agent received no HTTP response
  from the CDN (connection accepted, TLS completed, body never sent); the
  plain curl request returned 200 immediately.
- SHA-256: 504030af381b2ee828c3012ba91dcc9ea7cdbbcaa3297026acd500ed9c4b4e44
- Size: 186,343 bytes; 11,744 daily rows from 1981-09-01 to 2026-09-04;
  header `observation_date,DGS3MO`. 11253 rows carry a quote; 491 rows
  (79 of them on or after 2019-05-01, holidays such as 2023-11-23) have a
  blank value, which is how this download marks a missing day. No row uses
  the "." marker, but the reader skips "." and blank alike.
- Units: percent per year. The rate applied to a session is the most recent
  quoted observation dated strictly before it, so a holiday session takes the
  last quoted business day, converted as r = ln(1 + y/100). A session more
  than 10 calendar days after the last quote is refused as `rate_stale`.

## 2. SPY cash distributions: State Street

- File: raw/spdr-etf-historical-distributions.xlsx
- URL: https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx
  This is the workbook linked as "ETF Historical Distributions" from the SPY
  fund page (https://www.ssga.com/us/en/intermediary/etfs/state-street-spdr-sp-500-etf-trust-spy)
  via https://www.ssga.com/us/en/intermediary/resources/documents/etf-dividend-distributions.
  The fund page's own Distributions tab is filled by script from the same
  data and offers no per-fund download.
- Retrieved: 2026-09-09T03:42:24Z with curl.
- SHA-256: 1b952f87ca60ece4080b446d6c3b580f640d893ed33641797a2dd22dd61beca9
- Size: 575,400 bytes. One sheet, `dividend`, 13,227 data rows for every
  SPDR ETF; columns FUND NAME, TICKER, CUSIP, EX-DATE, RECORD DATE, PAYABLE
  DATE, DIVIDEND ($), SHORT TERM CAPITAL GAIN ($), LONG TERM CAPITAL GAIN
  ($), FREQUENCY. 135 SPY rows from 1993-03-19 to 2026-06-18; the 34 with
  ex-dates from 2018-01-01 are used. Every SPY row since 2018 has empty or
  zero capital-gain columns, so DIVIDEND ($) is the whole cash distribution.
  Amounts carry six decimals. SPY has never split.

## 3. AAPL cash dividends: Apple Investor Relations

- File: raw/apple-dividend-history-table.html
- URL: https://investor.apple.com/dividend-history/default.aspx
- Retrieval: curl received HTTP 403 with a bot-challenge page, so the page
  was opened in the in-app browser (page load about 2026-09-09T03:34:20Z),
  where it rendered without any challenge to solve. The dividend table's
  `outerHTML` was read from the DOM and saved verbatim. The browser computed
  the SHA-256 of that same string in place at 2026-09-09T03:50:46Z and it
  equals the hash of the saved file, so the file is byte-identical to the
  rendered table.
- SHA-256: c49fdd6e815165034a51deb3d0f3fe9444699d7165bbae54a9fcc2404024b8f1
- Size: 35,084 bytes. Columns Declared, Record, Payable, Amount, Type; 97
  rows (regular cash dividends and stock splits back to 1987). The page
  states: "Dividend amounts not split adjusted." Rows with record dates from
  2018-02-12 (35 regular cash dividends) are used.
- Ex-dates: Apple publishes declared, record, and payable dates but no
  ex-date. Each AAPL ex-date is taken from the DoltHub stocks `dividend`
  table row (section 4) whose ex_date falls in the five days up to the
  issuer's record date; all 35 matched exactly one row. Three record dates
  that fell on or after Veterans Day (2018-11-12, 2019-11-11, 2024-11-11)
  have ex-dates two business days earlier (2018-11-08, 2019-11-07,
  2024-11-08), consistent with the settlement holiday; a naive "one session
  before the record date" rule would have been wrong for those three, so the
  table, not the rule, is the source. The rule remains only as a flagged
  fallback in the parser and was not exercised.

## 4. DoltHub stocks database exports (ex-dates and cross-check)

- Files: raw/dolt-stocks-dividend-aapl-spy.csv (76 rows, AAPL and SPY
  ex-dates from 2017-01-01) and raw/dolt-stocks-split-aapl-spy.csv (AAPL
  7-for-1 on 2014-06-09 and 4-for-1 on 2020-08-31; no SPY splits).
- Source: local clone of post-no-preference/stocks at head commit
  rf9dcnjl1ouulr92j9u3d38nr4lnpvi4 (the same clone the v1 underlying bars
  came from), exported with `dolt sql -r csv` at 2026-09-09T03:50:43Z.
- SHA-256: 3e7dee014ad1e3cbe7b2056ab15d54755841b5854ccd9c6a7c14bf38d0250240
  (dividend), bb5ac4164132bf351052e7f4c95345c31878f3f7b33fddc1993fa176f5234681
  (split).
- Cross-check of issuer amounts against this table (parser `--crosscheck`):
  SPY agrees on every ex-date and on every amount to three decimals (the
  table rounds to three decimals; the issuer file carries six). AAPL agrees
  on every amount except the 2020-08-07 dividend, which the table shows as
  0.205 (split-adjusted) while the issuer shows the declared 0.82; the
  issuer value is used because it sits on the same share basis as the
  stored price on that date (section 5).

## 5. Share basis across the AAPL 4-for-1 split of 2020-08-31

Finding 1, dividends: Apple's amounts are not split-adjusted (the page says
so, and the quarterly amount goes from $0.82 with record dates in May and
August 2020 to $0.205 in November 2020). Each amount is on the share basis
that traded on its own ex-date.

Finding 2, prices: the stocks store holds unadjusted closes. AAPL closed at
499.23 on 2020-08-28 and at 129.04 on 2020-08-31 (raw/dolt-stocks and
full_underlying.csv agree), a 4:1 step with no back-adjustment of earlier
bars.

Decision: both series are on the as-traded basis at every date, so no
static rescaling of dividends.csv is correct on both sides of the split. A
trailing 365-day sum that straddles 2020-08-31 mixes bases, so the
dividend-series module rebases each dividend to the share basis of the price
it is divided by: for q_t = D_t / S_{t-1}, every AAPL dividend with an
ex-date before a split whose effective date is on or before t-1 is multiplied
by for_factor/to_factor (1/4 here) before summing. Stored prices are never
adjusted. Example: with t-1 = 2020-09-01 (close 134.18) the window holds the
0.77, 0.77, 0.82, and 0.82 pre-split dividends, rebased to 0.795 in total,
so q = 0.795 / 134.18 = 0.59%; with t-1 = 2020-08-28 (close 499.23) the same
four dividends sum to 3.18 unrebased, so q = 0.64%. The split itself is
recorded in splits.csv from the issuer's split row (payable column, starred
as the first split-adjusted trading date) and agrees with the DoltHub split
table and the price step.

## 7. VIX: FRED VIXCLS (Design C regimes)

- File: raw/VIXCLS.csv
- URL: https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS
- Retrieved: 2026-09-14T20:52:03Z with curl 8.7.1 (default User-Agent).
- SHA-256: 60f2ec1ea081cf27427b8a24930a2ebee7c1992aad14119e9380673cc85fb9c1
- Size: 161,204 bytes; 9,574 daily rows from 1990-01-02 to 2026-09-11, of
  which 9,272 carry a value and 302 are blank (missing days). Used only for
  the exploratory Design C regime breakdown: the regime of session t is the
  most recent observation dated strictly before t, and the terciles are
  computed over the evaluation window with the cut points recorded in
  docs/results/v2/design-c/breakdowns.json.

## 6. Parser and outputs

- scripts/build_external_inputs.py, SHA-256
  c45e9b53c4bb0ef2edc98394d7fb23c43b720874453a900815f934168be47246, run as
  `python scripts/build_external_inputs.py --start 2018-01-01 --crosscheck data/external/raw/dolt-stocks-dividend-aapl-spy.csv`.
- dividends.csv: 69 rows (35 AAPL, 34 SPY) with ex-dates from 2018-01-01;
  columns symbol, ex_date, amount; SHA-256
  7cc323daac11272eee3949729e7ee435ae865670ccb76b3424f80068cdbf39d2.
- splits.csv: AAPL,2020-08-31,4,1; SHA-256
  96053ba693b69c0e192622dadfd9dcb48db42d1829855334a067c69b17fb9fec.
- The 2018-01-01 start leaves a full 365-day lookback before the first
  stored session (2019-05-10). The Design A configs declare this start and
  the retrieval date (2026-09-09) as the covered history: a session whose
  365-day window starts before 2018-01-01 or ends after 2026-09-09 is refused
  (`dividend_history_unavailable` / `dividend_history_stale`) rather than
  summed over an incomplete history. Neither rule fires on any stored session.
  A session whose last underlying bar is more than 10 calendar days old is
  refused as `spot_prior_unavailable`; the bar file's only gaps are single
  days.
- Windows are literal calendar windows, so around quarter boundaries a
  window can hold three or five quarterly distributions instead of four
  (about 60 of the 1,839 bar days per symbol); q then steps by roughly a
  quarter for a few sessions. This follows the plan's definition and is left
  as is.

## 7. Underlying bars used for S_{t-1}

- File: raw/full_underlying.csv, a byte-identical copy of the v1 import's
  underlying export (`post-no-preference/stocks` ohlcv for SPY, QQQ, AAPL,
  2018-06-01 to 2026-09-04), SHA-256
  aa9e446dddf40682a68890a0b70f36a41c6d2f108d0777dddc1b7403801bc738, the same
  hash docs/results/manifest.json records for the import. Committed so the
  dividend yield's prior bar close is reproducible from the repository.

## 8. Refresh before the first fresh session (2026-09-15)

Retrieved on 2026-09-15 (UTC) under docs/LOCK.md step 1, in one pass, with
the locked configuration untouched: config/v2/C3.json still declares
history_end 2026-09-09, and the refreshed coverage is declared at run time
with `--dividend-history-end 2026-09-15`. The versions the pre-registered
Design A to C runs used remain at tag study-v2-locked and are hashed in each
run's significance.json; docs/results/manifest.json was rebuilt to the files
below.

- FRED DGS3MO, raw/DGS3MO.csv: retrieved 2026-09-15T22:46:32Z with curl 8.7.1
  (default User-Agent, HTTP 200). SHA-256
  95e9fcd7cbee9426d86b432ed6d681915dc4f4db2754912c6bfac006a62ba9c5; 186,435
  bytes; 11,750 rows from 1981-09-01 to 2026-09-14, 11,258 quoted and 492
  blank. Coverage end: 2026-09-14 (4.11 percent).
- Underlying bars, raw/full_underlying.csv: the local clone of
  post-no-preference/stocks was pulled at 2026-09-15T22:47:27Z to head
  a4pca9k9acjef0067beascu5468134fp ("ohlcv 2026-09-14 update") and exported
  at 2026-09-15T22:47:35Z with `dolt sql -r csv -q "SELECT date, act_symbol,
  open, high, low, close FROM ohlcv WHERE act_symbol IN ('AAPL','QQQ','SPY')
  AND date >= '2018-06-01' ORDER BY act_symbol, date"`. SHA-256
  57f6a8464afe3c831b418c9ff6d5b9126b3d8edf5c5a2eda1158d8bb344ef1f9; 320,407
  bytes; 6,241 rows (AAPL 2,080, QQQ 2,081, SPY 2,080). Every row of the
  previous file is present byte for byte; the 15 new rows are 2026-09-08 to
  2026-09-14 for the three symbols (2026-09-07 was Labor Day). Coverage end:
  2026-09-14 for every symbol.
- SPY distributions, raw/spdr-etf-historical-distributions.xlsx: retrieved
  2026-09-15T22:46:33Z with curl (HTTP 200). SHA-256
  18ae096941de56b8cb7e9f9d8041d23665c5aa99813163e578546e406c5fa137; 575,420
  bytes (13,228 data rows; 575,400 bytes and 13,227 rows at the previous
  retrieval, the additions concerning other funds). SPY rows unchanged:
  135 in total, 34 with ex-dates from 2018-01-01, last 2026-06-18.
- AAPL dividends, raw/apple-dividend-history-table.html: curl again received
  HTTP 403; the page was opened in the in-app browser (loaded
  2026-09-15T22:48:01Z), the dividend table's outerHTML read from the DOM
  and hashed in place: c49fdd6e815165034a51deb3d0f3fe9444699d7165bbae54a9fcc2404024b8f1,
  identical to the committed file, which was left as is. 97 rows; the latest
  regular cash dividend was declared July 30, 2026 with record date August
  10, 2026 ($0.27).
- DoltHub stocks exports, raw/dolt-stocks-dividend-aapl-spy.csv and
  raw/dolt-stocks-split-aapl-spy.csv: re-exported at 2026-09-15T22:47:35Z
  from the pulled clone with the section 4 queries; both byte-identical to
  the committed files (SHA-256 3e7dee01... and bb5ac416...). The options
  clone was pulled at 2026-09-15T22:47:31Z to head
  8u03gqhnbrni438fuvc3b1611fbblcui ("volatility_history 2026-09-14 update")
  to check availability only; it holds SPY and AAPL chains for 2026-09-08 to
  2026-09-14 (plus rows stamped 2026-09-07, a holiday) and nothing later, so
  no chain dated after the lock exists yet and none was read.
- Parser run 2026-09-15T22:49:04Z: `python scripts/build_external_inputs.py
  --start 2018-01-01 --crosscheck data/external/raw/dolt-stocks-dividend-aapl-spy.csv`
  (script SHA-256 c45e9b53... unchanged). dividends.csv and splits.csv are
  byte-identical to the committed files (SHA-256 7cc323da... and
  96053ba6...): 69 rows, AAPL last ex-date 2026-08-10, SPY last ex-date
  2026-06-18. The cross-check reports 24 differences, exactly as at the
  original retrieval: 23 three-decimal roundings of SPY amounts by the
  DoltHub table and the AAPL 2020-08-07 amount, which the table carries on
  the post-split basis (0.205) while the issuer's declared 0.82 is used
  (section 4); no date disagreement.
- Coverage declared for the fresh evaluation: distribution history
  2018-01-01 to 2026-09-15 (this retrieval), passed as
  `--dividend-history-end 2026-09-15`; bars through 2026-09-14; rate through
  2026-09-14. A fresh session t needs the bars through t (S_t, and S_t-1
  for q_t) and a distribution retrieval dated t-1 or later, so each fresh
  session repeats this pass on the morning its chain becomes available; the
  declared dates and hashes of every repeat are recorded in that session's
  prediction sidecar.

## 9. Refresh before the fresh session 2026-09-16 (2026-09-17)

Retrieved on 2026-09-17 (UTC) under docs/LOCK.md step 1, before the first
prediction of the fresh evaluation, in one pass; the locked configuration is
untouched and the coverage is declared at run time with
`--dividend-history-end 2026-09-17`. Only the rate series and the bar file
changed; every other file was re-retrieved and found byte-identical.

- FRED DGS3MO, raw/DGS3MO.csv: retrieved 2026-09-17T18:36:43Z with curl 8.7.1
  (default User-Agent, HTTP 200). SHA-256
  bbac0b34001201495cbf24dc797d68375400a0c6e311bc4a6bc35412598e278e; 186,451
  bytes; 11,751 rows from 1981-09-01 to 2026-09-15, 11,259 quoted and 492
  blank. Coverage end: 2026-09-15 (4.11 percent).
- Underlying bars, raw/full_underlying.csv: post-no-preference/stocks pulled
  at 2026-09-17T18:36:44Z to head k2llbsogjpra84f3t8ngjueg82kl489a ("ohlcv
  2026-09-16 update") and exported at 2026-09-17T18:36:50Z with the section 8
  query. SHA-256
  a6d11a5e7dafb15a21b65683c70636daf9ff0bfd414a516326c41ec5b9ddbded; 320,715
  bytes; 6,247 rows (AAPL 2,082, QQQ 2,083, SPY 2,082). The six new rows are
  2026-09-15 and 2026-09-16 for the three symbols; every previous row is
  present byte for byte. Coverage end: 2026-09-16 for every symbol.
- SPY distributions, raw/spdr-etf-historical-distributions.xlsx: retrieved
  2026-09-17T18:36:44Z (HTTP 200), byte-identical to the section 8 file
  (SHA-256 18ae096941de56b8cb7e9f9d8041d23665c5aa99813163e578546e406c5fa137).
  AAPL dividends, raw/apple-dividend-history-table.html: the page was loaded
  in the in-app browser at 2026-09-17T18:37:37Z (curl still receives HTTP
  403) and the table's outerHTML hashed in place:
  c49fdd6e815165034a51deb3d0f3fe9444699d7165bbae54a9fcc2404024b8f1, identical
  to the committed file. DoltHub dividend and split exports, re-exported at
  2026-09-17T18:36:50Z from the pulled clone: byte-identical. Parser run
  2026-09-17T18:37:47Z: dividends.csv and splits.csv byte-identical (SHA-256
  7cc323daac11272eee3949729e7ee435ae865670ccb76b3424f80068cdbf39d2 and
  96053ba693b69c0e192622dadfd9dcb48db42d1829855334a067c69b17fb9fec), AAPL
  last ex-date 2026-08-10, SPY 2026-06-18; the cross-check reports the same
  24 differences as section 8.
- The options clone was pulled at 2026-09-17T18:36:46Z to head
  vib1kogrtfgug6emknn4ine9nms5bmqa ("volatility_history 2026-09-16 update")
  to list availability only: it holds one session after the lock date,
  2026-09-16 (AAPL 194 rows, SPY 210), and no chain for it was read or
  imported before that session's prediction file was committed.
- Coverage declared for the fresh evaluation: distribution history 2018-01-01
  to 2026-09-17, passed as `--dividend-history-end 2026-09-17`; bars through
  2026-09-16; rate through 2026-09-15.

## 10. Automated refresh log (scripts/fresh_session.sh)

One row per run that preceded a prediction, appended by the script: the
retrieval timestamp, the SHA-256 and coverage end of each refreshed file, and
the history end declared to predict-locked. Apple's dividend page is not
retrievable without a browser, so the script keeps the section 3 file and
checks the refreshed DoltHub dividend table for an ex-date later than the
issuer histories; if one appears the run stops until the file is refreshed
by hand. This table is last in the file so that rows can be appended.

| Retrieved (UTC) | DGS3MO sha256 / last quote | Bars sha256 / last bar | SPDR workbook sha256 | dividends.csv sha256 / last AAPL, SPY ex-dates | history_end |
|---|---|---|---|---|---|
