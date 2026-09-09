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
  header `observation_date,DGS3MO`.
- Units: percent per year. A "." marks a missing observation; this file
  contains none, but the reader skips them. The rate applied to a session is
  the most recent observation dated strictly before it, converted as
  r = ln(1 + y/100).

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
  stored session (2019-05-10).
