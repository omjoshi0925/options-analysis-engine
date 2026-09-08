"""Fetch once, retain raw snapshots, and replay against fixed UTC timestamps."""
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import importlib.metadata
import json
import platform
import re
import numpy as np
import pandas as pd
from .volatility import ESTIMATORS, realized_volatility

YEAR_SECONDS = 365.0*24*3600


def utc_timestamp(value):
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError("Timestamp must include a timezone, e.g. 2026-09-08T20:00:00Z")
    return timestamp.tz_convert("UTC")


def time_to_expiry(expiration, as_of, expiry_hour=16, exchange_tz="America/New_York"):
    """ACT/365F, fractional seconds. PM expiry convention, not an exchange calendar."""
    if not 0 <= expiry_hour <= 23:
        raise ValueError("expiry_hour must be between 0 and 23")
    end = pd.Timestamp(expiration)
    if end.tzinfo is not None:
        end = end.tz_convert("UTC")
    else:
        end = (end.normalize()+pd.Timedelta(hours=expiry_hour)).tz_localize(exchange_tz).tz_convert("UTC")
    return (end-utc_timestamp(as_of)).total_seconds()/YEAR_SECONDS


def environment_versions():
    out = {"python": platform.python_version()}
    for name in ("numpy", "pandas", "scipy", "matplotlib", "yfinance", "streamlit"):
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            out[name] = "not installed"
    return out


def write_snapshot(raw, folder, metadata, histories=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    raw.to_csv(folder/"raw_options.csv", index=False)
    if histories is not None and not histories.empty:
        histories.to_csv(folder/"underlying_history.csv", index=False)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob("*.csv")}
    meta = {**metadata, "schema_version": 1, "csv_sha256": hashes, "environment": environment_versions()}
    (folder/"metadata.json").write_text(json.dumps(meta, indent=2, allow_nan=False)+"\n")
    return folder


def read_snapshot(folder):
    folder = Path(folder)
    meta = json.loads((folder/"metadata.json").read_text())
    if meta.get("schema_version") != 1 or "raw_options.csv" not in meta.get("csv_sha256", {}):
        raise ValueError("Unsupported or incomplete snapshot manifest")
    for filename, expected in meta["csv_sha256"].items():
        if Path(filename).name != filename:
            raise ValueError("Unsafe snapshot manifest filename")
        if hashlib.sha256((folder/filename).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Snapshot checksum mismatch: {filename}")
    return pd.read_csv(folder/"raw_options.csv"), meta


def fetch_options(tickers, rate, dividend_yields, expirations=3, volatility=None,
                  history_window=60, expiry_hour=16, estimator="close_to_close"):
    """US stock/ETF convention. Inputs r/q are explicit assumptions, never fetched defaults.

    A captured chain's underlying quote is preferred. Fallback daily Close is
    unadjusted; adjusted historical Close is used only to estimate realized vol.
    Historical volatility excludes today's potentially incomplete daily bar.
    Close-to-close uses adjusted closes; the range estimators use unadjusted OHLC.
    """
    import yfinance as yf
    if expirations < 1 or history_window < 2 or not np.isfinite(rate):
        raise ValueError("Invalid acquisition parameters")
    if volatility is not None and (not np.isfinite(volatility) or volatility <= 0):
        raise ValueError("Fixed volatility must be finite and positive")
    if estimator not in ESTIMATORS:
        raise ValueError(f"estimator must be one of {ESTIMATORS}")
    frames, histories, failures, assumptions = [], [], [], {}
    started = datetime.now(timezone.utc).isoformat()
    for symbol in dict.fromkeys(str(s).upper() for s in tickers):
        if not re.fullmatch(r"[A-Z0-9.^=_-]+", symbol):
            raise ValueError(f"Invalid ticker symbol: {symbol}")
        if symbol not in dividend_yields or not np.isfinite(dividend_yields[symbol]):
            raise ValueError(f"Supply an explicit dividend yield for {symbol}, including zero")
        q = float(dividend_yields[symbol])
        ticker = yf.Ticker(symbol)
        try:
            hist = ticker.history(period="1y", auto_adjust=False, actions=False)
            if hist.empty or "Close" not in hist or hist.Close.dropna().empty:
                raise ValueError("No underlying daily prices returned")
            spot_close = float(hist.Close.dropna().iloc[-1])
            last_session = str(hist.Close.dropna().index[-1])
            today_ny = pd.Timestamp.now(tz="America/New_York").date()
            complete = hist.loc[[x.date() < today_ny for x in hist.index]]
            vol_field = "Adj Close" if "Adj Close" in complete else "Close"
            closes = complete[vol_field].dropna().tail(history_window+1)
            if (closes <= 0).any():
                raise ValueError("Nonpositive historical price")
            if volatility is not None:
                sigma, source = float(volatility), "user_fixed"
            else:
                if estimator == "close_to_close":
                    bars, field = pd.DataFrame({"close": closes.to_numpy()}), vol_field
                else:
                    bars, field = complete[[c for c in ("Open", "High", "Low", "Close") if c in complete]], "unadjusted OHLC"
                sigma = realized_volatility(bars, estimator, history_window).sigma
                source = f"realized_{history_window}_sessions_{estimator}_{field}"
            if not np.isfinite(sigma) or sigma <= 0:
                raise ValueError("Invalid independent baseline volatility")
            history = hist.reset_index()
            history["symbol"] = symbol
            histories.append(history)
            assumptions[symbol] = dict(r=rate, q=q, baseline_sigma=sigma,
                                       baseline_source=source,
                                       history_end=str(closes.index[-1]), spot_fallback_session=last_session)
            selected_expiries = list(ticker.options)[:expirations]
            if not selected_expiries:
                raise ValueError("No options expirations returned")
        except Exception as exc:  # External provider boundary: retain failure and continue other assets.
            failures.append(dict(symbol=symbol, stage="history_or_expirations", error=f"{type(exc).__name__}: {exc}"))
            continue
        for expiration in selected_expiries:
            try:
                chain = ticker.option_chain(expiration)
                captured = datetime.now(timezone.utc).isoformat()
                underlying = getattr(chain, "underlying", {}) or {}
                spot = underlying.get("regularMarketPrice")
                if spot is None or not np.isfinite(float(spot)) or float(spot) <= 0:
                    spot = spot_close
                    spot_source = "unadjusted_daily_close_fallback"
                    spot_time = None
                else:
                    spot_source = "chain_underlying_regularMarketPrice"
                    epoch = underlying.get("regularMarketTime")
                    spot_time = pd.Timestamp(epoch, unit="s", tz="UTC").isoformat() if epoch else None
                for frame, kind in ((chain.calls, "call"), (chain.puts, "put")):
                    if frame.empty:
                        failures.append(dict(symbol=symbol, expiration=expiration, stage=kind, error="Empty chain"))
                        continue
                    frame = frame.copy()
                    fields = dict(symbol=symbol, option_type=kind, expiration=expiration, as_of=captured,
                                  spot=float(spot), spot_source=spot_source, spot_timestamp=spot_time,
                                  spot_session=last_session, r=rate, q=q, baseline_sigma=sigma,
                                  baseline_source=assumptions[symbol]["baseline_source"],
                                  exercise_style="american", data_kind="market", expiry_hour=expiry_hour)
                    for key, value in fields.items():
                        frame[key] = value
                    frames.append(frame)
            except Exception as exc:
                failures.append(dict(symbol=symbol, expiration=expiration, stage="chain", error=f"{type(exc).__name__}: {exc}"))
    metadata = dict(data_kind="market", provider="Yahoo Finance via yfinance", acquisition_started=started,
                    acquisition_finished=datetime.now(timezone.utc).isoformat(), requested_tickers=list(tickers),
                    requested_expirations=expirations, assumptions=assumptions, failures=failures,
                    expiry_convention=f"{expiry_hour:02d}:00 America/New_York; ACT/365F; US PM assumption",
                    quote_timestamp_available=False,
                    notes=["Capture time is not quote time. lastTradeDate is a trade timestamp, not a bid/ask timestamp.",
                           "US equity/ETF options are treated as American; BSM results are European-equivalent diagnostics.",
                           "Daily fallback spot is not synchronized with option quotes. No exchange calendar is applied."])
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), metadata,
            pd.concat(histories, ignore_index=True) if histories else pd.DataFrame())


@dataclass(frozen=True)
class FilterConfig:
    min_volume: int = 0
    min_open_interest: int = 10
    max_relative_spread: float = 0.5
    min_days: float = 0.0
    max_days: float = 730.0
    max_last_trade_age_days: float | None = None

    def __post_init__(self):
        for key in ("min_volume", "min_open_interest", "max_relative_spread", "min_days", "max_days"):
            if not np.isfinite(getattr(self, key)) or getattr(self, key) < 0:
                raise ValueError(f"{key} must be finite and nonnegative")
        if self.max_relative_spread <= 0 or self.max_days <= self.min_days:
            raise ValueError("Invalid spread or maturity thresholds")
        if self.max_last_trade_age_days is not None and (not np.isfinite(self.max_last_trade_age_days) or self.max_last_trade_age_days < 0):
            raise ValueError("Trade age threshold must be finite and nonnegative")


def filter_options(raw, config=None):
    config = config or FilterConfig()
    required = {"symbol", "option_type", "expiration", "as_of", "spot", "strike", "bid", "ask", "r", "q", "baseline_sigma"}
    if missing := required-set(raw.columns):
        raise ValueError(f"Missing raw columns: {sorted(missing)}")
    df = raw.copy().reset_index(drop=True)
    df.insert(0, "row_id", np.arange(len(df)))
    numeric = ("spot", "strike", "bid", "ask", "r", "q", "baseline_sigma", "volume", "openInterest", "impliedVolatility")
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce") if col in df else np.nan
    reasons = [[] for _ in range(len(df))]

    def reject(mask, reason):
        for idx in np.flatnonzero(np.asarray(mask)):
            reasons[idx].append(reason)

    times = []
    for row in df.to_dict("records"):
        try:
            times.append(time_to_expiry(row["expiration"], row["as_of"], int(row.get("expiry_hour", 16))))
        except (ValueError, TypeError, OverflowError):
            times.append(np.nan)
    df["T"] = times
    df["days_to_expiry"] = df["T"]*365  # calendar, fractional
    reject(~np.isfinite(df["T"]), "invalid_timestamp")
    reject(df["T"] <= 0, "expired")
    reject((df.days_to_expiry < config.min_days) | (df.days_to_expiry > config.max_days), "maturity_filter")
    reject(~df.option_type.isin(["call", "put"]), "invalid_option_type")
    for col in ("spot", "strike", "baseline_sigma"):
        reject(~np.isfinite(df[col]) | (df[col] <= 0), f"invalid_{col}")
    for col in ("r", "q"):
        reject(~np.isfinite(df[col]), f"invalid_{col}")
    reject(~np.isfinite(df.bid) | ~np.isfinite(df.ask) | (df.bid <= 0) | (df.ask <= 0), "invalid_quote")
    reject(df.ask < df.bid, "crossed_market")
    df["mid"] = (df.bid+df.ask)/2
    df["spread"] = df.ask-df.bid
    df["relative_spread"] = df.spread/df.mid.where(df.mid > 0)
    reject(df.relative_spread > config.max_relative_spread, "wide_spread")
    for col, threshold, reason in (("volume", config.min_volume, "low_or_missing_volume"),
                                   ("openInterest", config.min_open_interest, "low_or_missing_open_interest")):
        reject((df[col] < 0) | (df[col].notna() & ~np.isfinite(df[col])), f"invalid_{col}")
        if threshold > 0:
            reject(df[col].isna() | (df[col] < threshold), reason)
    trade = pd.to_datetime(df.get("lastTradeDate", pd.Series(pd.NaT, index=df.index)), utc=True, errors="coerce")
    captured = pd.to_datetime(df.as_of, utc=True, errors="coerce", format="mixed")
    df["last_trade_age_days"] = (captured-trade).dt.total_seconds()/86400
    if config.max_last_trade_age_days is not None:
        reject(df.last_trade_age_days.isna() | (df.last_trade_age_days > config.max_last_trade_age_days) |
               (df.last_trade_age_days < 0), "last_trade_age_filter")
    key = ["symbol", "option_type", "expiration", "strike", "as_of"]
    reject(df.duplicated(key, keep=False), "duplicate_contract_snapshot")
    df["accepted"] = [not reason for reason in reasons]
    df["filter_reasons"] = [";".join(reason) for reason in reasons]
    df["log_moneyness"] = np.log((df.spot/df.strike).where((df.spot > 0) & (df.strike > 0)))
    df["forward_log_moneyness"] = df.log_moneyness + (df.r-df.q)*df["T"]
    return df.loc[df.accepted].copy(), df
