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
