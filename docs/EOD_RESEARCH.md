# Free historical data and walk-forward research

## The daily_eod tier

The strict tier exists because intraday quote timestamps from the production
feed can be verified. Free historical archives cannot offer that, so version
3.2 adds a second, honestly labeled tier instead of quietly loosening the
strict one. In the `daily_eod` tier every quote is stamped at the exchange
close of its session, synchrony of the closing snapshot is assumed rather than
verified, and the provider/feed labels (`dolt_eod` / `historical_eod`) make the
provenance permanent. The two tiers never mix: a config is validated to one
tier, ineligible rows from the other tier are stored with a
`wrong_feed_for_daily_eod_tier` (or `unverified_feed`) reason, and results from
each tier must be reported as such. EOD data supports cross-sectional and
time-series pricing research; it does not support microstructure claims.

## Getting the data, free and without an account

The public DoltHub database `post-no-preference/options` publishes end-of-day
US option chains (roughly 2019 onward, ~2,000 symbols) with bid, ask, and
implied volatility; the companion `post-no-preference/stocks` database
publishes daily underlying OHLC bars. Both clone freely:

```bash
brew install dolt   # or see dolt install docs for Linux
dolt clone post-no-preference/options && cd options
dolt sql -q "DESCRIBE option_chain"   # verify column names before exporting
dolt sql -r csv -q "SELECT date, act_symbol, expiration, strike, call_put, bid, ask, vol FROM option_chain WHERE act_symbol = 'SPY'" > ../spy_chain.csv
cd .. && dolt clone post-no-preference/stocks && cd stocks
dolt sql -r csv -q "SELECT date, act_symbol, open, high, low, close FROM ohlcv WHERE act_symbol = 'SPY'" > ../spy_underlying.csv
```

Check the database's stated license on DoltHub before publishing results built
on it, and cite the source in any writeup. Then:

```bash
python -m options_engine init-live --provider dolt_eod --config config/eod.json
# edit tickers, rate, and dividend assumptions
python -m options_engine import-eod --config config/eod.json --chain-csv spy_chain.csv --underlying-csv spy_underlying.csv
```

The importer writes one immutable snapshot per session, computes the baseline
volatility for each session from strictly prior underlying bars only (the
configured estimator applies), stamps every quote at that session's XNYS close
including early closes, and ingests through the same deduplicating store and
audit trail as live collection. Re-importing the same export is a no-op. The
dataset publishes no volume or open interest, so liquidity screening in this
tier rests on relative spreads; `min_open_interest` must be 0 and the columns
are stored as missing rather than fabricated.

## Walk-forward evaluation

`python -m options_engine walk-forward --config config/eod.json --output results/wf`

One fold per evaluated session: train on everything before an embargo gap,
re-select the ridge penalty on the training tail, refit, and score the next
unseen session against the independent baseline. Per-quote losses (squared
spot-normalized pricing error against the contemporaneous midpoint) are
averaged to one loss per session before any statistics are computed, because
quotes within a session are strongly dependent.

Significance is reported three ways, and they answer different questions:

- The model win rate says how often the model session-loss beat the baseline.
- The Diebold-Mariano statistic (Harvey-Leybourne-Newbold small-sample
  correction, Student-t reference) tests whether the mean session-level loss
  differential is distinguishable from zero.
- A circular block bootstrap gives a confidence interval for that mean
  differential while respecting serial dependence across sessions.

These can disagree, and that is informative: a low win rate with a positive
mean differential means rare large wins, and a p-value near one with a
positive point estimate means the sample cannot support the claim. Report
whatever comes out. A null result from this pipeline is a finding, not a
failure, and the promotion gate in `learning.train` remains the only mechanism
that activates a model for scoring.

Every number this produces measures contemporaneous pricing accuracy on later
sessions under the maintained rate and dividend assumptions. None of it is a
forecast of option returns, and none of it is a tradable claim.

## Study v2: dated carry inputs and frozen observation sets (3.3.0)

Design A of docs/RESEARCH_PLAN.md reprices the same quotes under four carry
configurations. The inputs live under `data/external/` (see PROVENANCE.md
there) and the configurations under `config/v2/`: C0 constant r and q (v1),
C1 historical r, C2 historical q, C3 both.

```bash
python -m options_engine observation-set build \
  --configs config/v2/C0.json config/v2/C1.json config/v2/C2.json config/v2/C3.json \
  --out docs/results/v2/observation-set-A.csv
python -m options_engine walk-forward --config config/v2/C0.json \
  --observation-set docs/results/v2/observation-set-A.csv \
  --output docs/results/v2/design-a/C0 --min-train-sessions 120 --gap 1 \
  --window rolling --max-train-sessions 250
```

For session t the rate is the last DGS3MO quote dated strictly before t,
converted as ln(1 + y/100); the dividend yield is the sum of distributions
with ex-dates in the 365 days ending at t-1, rebased to the share basis of the
last underlying bar before t, divided by that bar's close. Rows whose inputs
are unavailable or whose implied volatility cannot be identified under a
configuration are dropped from the set with the reason counted in
`observation-set-A.drops.json`; the set is the intersection over all four
configurations, so every run shares its rows, sessions, and fold boundaries.
`walk-forward --observation-set` refuses to run unless the set is fully
present in the store, nothing more drops under the run's carry, and the config
is one the set was built with (`--allow-partial` overrides and records the
problems in significance.json).

Rules the series module applies beyond the plan's definitions, all recorded
in each run's significance.json: a rate quote older than `stale_days` (10)
before the session is refused; a dividend window that starts before the
declared `history_start` or ends after `history_end` is refused; an underlying
bar older than `max_bar_gap_days` (10) is refused. Under a configuration's r
and q the implied-volatility learning target is re-solved from the same mid,
and rows whose target does not identify, or leaves the v1 range [3%, 300%],
are drop reasons (`iv_not_identified`, `iv_outside_training_range`); constant
v1 carry reproduces every stored target exactly.

Column semantics: in `export` output, `r`, `q`, `iv_brent_*`, `baseline_*` and
the bound columns are the values stored at import (constant v1 carry), while
`effective_r`/`effective_q` are the config's carry for that session and symbol
(NaN with a `carry_failure` reason when unavailable). In fold tables,
`r_effective` and `q_effective_<symbol>` are the carry the fold was priced and
trained under; `baseline_mse`/`model_mse` are the session losses behind the
tests, `rho = 1 - sqrt(model_mse)/sqrt(baseline_mse)`, `d = baseline_mse -
model_mse`. The config/v2 files sit one directory deeper than
config/eod-full.json, so their `data_root` reads `../../data/eod-live-full`
and resolves to the same store; every other field except rate and dividend is
identical.

