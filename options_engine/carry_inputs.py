"""Rate and dividend inputs for pricing and features: constant (v1) or dated series.

Alignment rules, fixed by docs/RESEARCH_PLAN.md section 2 and Amendment 2:

- Rate for session t: the most recent series quote dated strictly before t,
  converted to a continuously compounded rate, r = ln(1 + y/100) for a quote
  in percent.
- Dividend yield for session t: q_t = D_t / S_{t-1}, where D_t is the sum of
  cash distributions with ex-dates in the 365 days ending at t-1 inclusive
  and S_{t-1} is the last underlying bar close dated strictly before t. Each
  distribution is rebased to the share basis of that bar: multiplied by
  for_factor/to_factor for every split effective after its ex-date and on or
  before the bar date. Stored prices are never adjusted.

Anything missing raises InputUnavailable with a machine-readable reason so
the observation-set builder can record it as a drop instead of guessing.
"""
from __future__ import annotations

import bisect
import csv
import datetime as dt
import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .iv import implied_volatility

IV_TRAINING_RANGE = (.03, 3.0)   # the same bounds store.eod_training_quality applies
FAILURE_REASONS = ("rate_unavailable", "rate_stale", "spot_prior_unavailable", "dividend_history_unavailable",
                   "dividend_history_stale", "iv_not_identified", "iv_outside_training_range")


class InputUnavailable(ValueError):
    """A dated input the configuration requires does not exist for this session."""

    def __init__(self, reason, detail=""):
        if reason not in FAILURE_REASONS:
            raise ValueError(f"Unknown failure reason {reason!r}")
        super().__init__(f"{reason} ({detail})" if detail else reason)
        self.reason = reason


def as_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return pd.Timestamp(value).date()


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RateSeries:
    """Dated rate quotes; the rate for a session is the last quote dated strictly before it."""

    def __init__(self, dates, rates, source=None, stale_days=10):
        if isinstance(stale_days, bool) or not isinstance(stale_days, int) or stale_days < 1:
            raise ValueError("stale_days must be a positive integer")
        self.stale_days = stale_days
        pairs = sorted(zip((as_date(d) for d in dates), (float(r) for r in rates), strict=True))
        if not pairs:
            raise ValueError("Rate series is empty")
        if len({d for d, _ in pairs}) != len(pairs):
            raise ValueError("Rate series has duplicate dates")
        self.dates = [d for d, _ in pairs]
        self.rates = [r for _, r in pairs]
        self.source = source

    @classmethod
    def from_csv(cls, path, units="percent", column=None, stale_days=10):
        """FRED layout: a date column then the value column; "." or a blank marks a missing day and is skipped."""
        if units not in ("percent", "decimal"):
            raise ValueError("units must be percent or decimal")
        dates, rates = [], []
        with open(path, newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader)
            value_column = 1 if column is None else header.index(column)
            for row in reader:
                if len(row) <= value_column:
                    continue
                text = row[value_column].strip()
                if text in ("", "."):
                    continue
                quote = float(text)/(100.0 if units == "percent" else 1.0)
                if not math.isfinite(quote) or quote <= -1:
                    raise ValueError(f"Invalid rate quote {text!r} on {row[0]}")
                dates.append(as_date(row[0]))
                rates.append(math.log1p(quote))
        return cls(dates, rates, source=str(path), stale_days=stale_days)

    def quote_before(self, day):
        day = as_date(day)
        index = bisect.bisect_left(self.dates, day)
        if index == 0:
            raise InputUnavailable("rate_unavailable", f"no quote dated before {day}")
        quote_date = self.dates[index-1]
        if (day-quote_date).days > self.stale_days:
            raise InputUnavailable("rate_stale", f"last quote {quote_date} is more than {self.stale_days} days before {day}")
        return quote_date, self.rates[index-1]

    def rate_for(self, day):
        return self.quote_before(day)[1]


class DividendSeries:
    """Trailing cash-distribution yield on the share basis of the prior bar close."""

    def __init__(self, dividends, bars, splits=None, window_days=365, stale_days=100, history_start=None, history_end=None,
                 max_bar_gap_days=10, source=None):
        if isinstance(window_days, bool) or not isinstance(window_days, int) or window_days < 1:
            raise ValueError("window_days must be a positive integer")
        if isinstance(stale_days, bool) or not isinstance(stale_days, int) or stale_days < 1:
            raise ValueError("stale_days must be a positive integer")
        self.window_days, self.stale_days, self.source = window_days, stale_days, source
        self.history_start = as_date(history_start) if history_start is not None else None
        self.history_end = as_date(history_end) if history_end is not None else None
        if isinstance(max_bar_gap_days, bool) or not isinstance(max_bar_gap_days, int) or max_bar_gap_days < 1:
            raise ValueError("max_bar_gap_days must be a positive integer")
        self.max_bar_gap_days = max_bar_gap_days
        dividends = _normalize_columns(dividends, {"symbol", "ex_date", "amount"})
        bars = _normalize_columns(bars, {"symbol", "date", "close"})
        splits = _normalize_columns(splits, {"symbol", "ex_date", "to_factor", "for_factor"}) if splits is not None else None
        self._dividends, self._history, self._bars, self._splits = {}, {}, {}, {}
        for symbol, group in dividends.groupby("symbol"):
            pairs = sorted(zip((as_date(d) for d in group.ex_date), (float(a) for a in group.amount), strict=True))
            if any(a < 0 or not math.isfinite(a) for _, a in pairs):
                raise ValueError(f"Negative or non-finite distribution for {symbol}")
            self._dividends[symbol] = ([d for d, _ in pairs], [a for _, a in pairs])
            # Coverage runs from the declared history_start (the parser's --start) or, conservatively, the first ex-date,
            # to the declared history_end (the retrieval date) or, conservatively, the last ex-date plus stale_days.
            self._history[symbol] = (self.history_start or pairs[0][0], self.history_end or pairs[-1][0]+dt.timedelta(days=stale_days))
        for symbol, group in bars.groupby("symbol"):
            pairs = sorted(zip((as_date(d) for d in group.date), (float(c) for c in group.close), strict=True))
            self._bars[symbol] = ([d for d, _ in pairs], [c for _, c in pairs])
        if splits is not None:
            for symbol, group in splits.groupby("symbol"):
                events = []
                for row in group.itertuples(index=False):
                    to, for_ = float(row.to_factor), float(row.for_factor)
                    if not (to > 0 and for_ > 0):
                        raise ValueError(f"Split factors must be positive for {symbol}")
                    events.append((as_date(row.ex_date), for_/to))
                self._splits[symbol] = sorted(events)

    @classmethod
    def from_csv(cls, dividends_path, bars_path, splits_path=None, window_days=365, stale_days=100, history_start=None,
                 history_end=None, max_bar_gap_days=10):
        splits = pd.read_csv(splits_path) if splits_path else None
        return cls(pd.read_csv(dividends_path), pd.read_csv(bars_path), splits, window_days, stale_days, history_start, history_end,
                   max_bar_gap_days,
                   source=dict(dividends=str(dividends_path), bars=str(bars_path), splits=str(splits_path) if splits_path else None))

    def prior_close(self, symbol, day):
        """The last bar dated strictly before `day`."""
        day = as_date(day)
        if symbol not in self._bars:
            raise InputUnavailable("spot_prior_unavailable", f"no bars for {symbol}")
        dates, closes = self._bars[symbol]
        index = bisect.bisect_left(dates, day)
        if index == 0:
            raise InputUnavailable("spot_prior_unavailable", f"no bar for {symbol} before {day}")
        if (day-dates[index-1]).days > self.max_bar_gap_days:
            raise InputUnavailable("spot_prior_unavailable", f"last bar for {symbol} ({dates[index-1]}) is more than {self.max_bar_gap_days} days before {day}")
        return dates[index-1], closes[index-1]

    def basis_factor(self, symbol, ex_date, bar_date):
        """Product of for/to over splits effective after the ex-date and on or before the bar date."""
        factor = 1.0
        for split_date, ratio in self._splits.get(symbol, ()):
            if ex_date < split_date <= bar_date:
                factor *= ratio
        return factor

    def yield_for(self, symbol, day):
        """q for session `day`; returns (q, details)."""
        day = as_date(day)
        if symbol not in self._dividends:
            raise InputUnavailable("dividend_history_unavailable", f"no distribution history for {symbol}")
        window_start, window_end = day-dt.timedelta(days=self.window_days), day-dt.timedelta(days=1)
        first, last = self._history[symbol]
        if window_start < first:
            raise InputUnavailable("dividend_history_unavailable", f"{symbol} history starts {first}, window starts {window_start}")
        if window_end > last:
            raise InputUnavailable("dividend_history_stale", f"{symbol} history covers through {last}, window ends {window_end}")
        bar_date, close = self.prior_close(symbol, day)
        if not close > 0:
            raise InputUnavailable("spot_prior_unavailable", f"nonpositive close for {symbol} on {bar_date}")
        dates, amounts = self._dividends[symbol]
        lo, hi = bisect.bisect_left(dates, window_start), bisect.bisect_right(dates, window_end)
        declared = amounts[lo:hi]
        rebased = [a*self.basis_factor(symbol, d, bar_date) for d, a in zip(dates[lo:hi], declared, strict=True)]
        total = float(sum(rebased))
        return total/close, dict(bar_date=bar_date, close=close, window_start=window_start, window_end=window_end,
                                 distributions=len(declared), declared_sum=float(sum(declared)), rebased_sum=total)


def _normalize_columns(frame, required):
    frame = frame.rename(columns={"act_symbol": "symbol"})
    missing = required-set(frame.columns)
    if missing:
        raise ValueError(f"Missing columns {sorted(missing)}; have {sorted(frame.columns)}")
    return frame


class CarryInputs:
    """Effective r and q per session and symbol under one configuration."""

    def __init__(self, rate_spec, dividend_spec, base_dir=None):
        def resolve(path):
            path = Path(path).expanduser()
            if path.is_absolute():
                return str(path)
            if base_dir is None:
                raise ValueError(f"Relative series path {path} needs the config file's directory; load the config with LiveConfig.load")
            return str((Path(base_dir)/path).resolve())
        self.rate_spec, self.dividend_spec = dict(rate_spec), dict(dividend_spec)
        if rate_spec["mode"] == "constant":
            self._rate, self._rate_series = float(rate_spec["value"]), None
        else:
            self._rate = None
            self._rate_series = RateSeries.from_csv(resolve(rate_spec["path"]), units=rate_spec.get("units", "percent"),
                                                    column=rate_spec.get("column"), stale_days=int(rate_spec.get("stale_days", 10)))
        if dividend_spec["mode"] == "constant":
            self._yields, self._dividend_series = {k: float(v) for k, v in dividend_spec["yields"].items()}, None
        else:
            self._yields = None
            self._dividend_series = DividendSeries.from_csv(
                resolve(dividend_spec["path"]), resolve(dividend_spec["bars"]),
                resolve(dividend_spec["splits"]) if dividend_spec.get("splits") else None,
                window_days=int(dividend_spec.get("window_days", 365)), stale_days=int(dividend_spec.get("stale_days", 100)),
                history_start=dividend_spec.get("history_start"), history_end=dividend_spec.get("history_end"),
                max_bar_gap_days=int(dividend_spec.get("max_bar_gap_days", 10)))

    @classmethod
    def from_config(cls, config):
        return cls(config.rate_spec, config.dividend_spec, getattr(config, "base_dir", None))

    @property
    def rate_mode(self):
        return self.rate_spec["mode"]

    @property
    def dividend_mode(self):
        return self.dividend_spec["mode"]

    def rate_for(self, day):
        return self._rate if self._rate_series is None else self._rate_series.rate_for(day)

    def yield_for(self, symbol, day):
        if self._dividend_series is None:
            if symbol not in self._yields:
                raise InputUnavailable("dividend_history_unavailable", f"no constant yield for {symbol}")
            return self._yields[symbol]
        return self._dividend_series.yield_for(symbol, day)[0]

    def describe(self):
        """Modes, resolved paths, and file hashes, for significance.json and the manifest."""
        rate = dict(mode=self.rate_mode)
        if self._rate_series is None:
            rate["value"] = self._rate
        else:
            rate.update(path=self._rate_series.source, sha256=file_digest(self._rate_series.source),
                        alignment="strictly_prior", units=self.rate_spec.get("units", "percent"), stale_days=self._rate_series.stale_days,
                        quotes=len(self._rate_series.dates), first_quote=str(self._rate_series.dates[0]),
                        last_quote=str(self._rate_series.dates[-1]))
        dividend = dict(mode=self.dividend_mode)
        if self._dividend_series is None:
            dividend["yields"] = dict(self._yields)
        else:
            series = self._dividend_series
            dividend.update(window_days=series.window_days, stale_days=series.stale_days, max_bar_gap_days=series.max_bar_gap_days,
                            history_start=str(series.history_start) if series.history_start else None,
                            history_end=str(series.history_end) if series.history_end else None,
                            files={name: (dict(path=path, sha256=file_digest(path)) if path else None) for name, path in series.source.items()})
        return dict(rate=rate, dividend=dividend)


def effective_carry(frame, carry):
    """One row per (session_date, symbol): effective r and q, or the reason they are unavailable."""
    rows = []
    for (day, symbol), _ in frame.groupby(["session_date", "symbol"], sort=True).groups.items():
        record = dict(session_date=day, symbol=symbol, effective_r=np.nan, effective_q=np.nan, carry_failure="")
        try:
            rate, dividend_yield = carry.rate_for(day), carry.yield_for(symbol, day)
        except InputUnavailable as exc:
            record["carry_failure"] = exc.reason   # both values stay NaN: a row is priced under a full carry or not at all
        else:
            record["effective_r"], record["effective_q"] = rate, dividend_yield
        rows.append(record)
    return pd.DataFrame(rows, columns=["session_date", "symbol", "effective_r", "effective_q", "carry_failure"])


def apply_carry(frame, carry, resolve_iv=True):
    """Set r and q on every row from `carry`, re-solve the implied-volatility target under them, and split off failures.

    Returns (kept, failures). `kept` carries effective_r/effective_q columns and, when resolve_iv is set, an
    iv_brent_* block solved under the effective carry so the learning target is consistent with the pricing
    inputs. `failures` lists observation_id, session_date, symbol, reason for rows that cannot be used.
    """
    frame = frame.copy()
    if "observation_id" not in frame:
        frame["observation_id"] = [f"row-{i}" for i in range(len(frame))]
    table = effective_carry(frame, carry)
    merged = frame.merge(table, on=["session_date", "symbol"], how="left")
    failed = merged.carry_failure != ""
    failures = [merged.loc[failed, ["observation_id", "session_date", "symbol"]].assign(reason=merged.loc[failed, "carry_failure"])]
    kept = merged.loc[~failed].copy()
    kept["r"], kept["q"] = kept.effective_r.astype(float), kept.effective_q.astype(float)
    if resolve_iv and len(kept):
        solved = []
        for row in kept.itertuples(index=False):
            result = implied_volatility(row.mid, row.spot, row.strike, row.T, row.r, row.q, row.option_type)
            if not result.converged or result.poorly_identified:
                solved.append(("iv_not_identified", result))
            elif not IV_TRAINING_RANGE[0] <= result.volatility <= IV_TRAINING_RANGE[1]:
                solved.append(("iv_outside_training_range", result))
            else:
                solved.append(("", result))
        reasons = np.array([reason for reason, _ in solved], dtype=object)
        for key in ("volatility", "converged", "status", "iterations", "residual", "vega", "poorly_identified", "fallback_used"):
            kept["iv_brent_"+key] = [getattr(result, key) for _, result in solved]
        if "identified_iv" in kept:
            kept["identified_iv"] = kept.iv_brent_volatility.where(reasons == "")
        bad = reasons != ""
        failures.append(kept.loc[bad, ["observation_id", "session_date", "symbol"]].assign(reason=reasons[bad]))
        kept = kept.loc[~bad].copy()
    failures = pd.concat(failures, ignore_index=True) if failures else pd.DataFrame(columns=["observation_id", "session_date", "symbol", "reason"])
    return kept.reset_index(drop=True), failures.reset_index(drop=True)
