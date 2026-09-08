"""Read-only provider adapters. No account, order, or trading endpoints are called."""
from pathlib import Path
import json
import os
import time
import numpy as np
import pandas as pd
import requests
from .data import fetch_options
from .volatility import realized_volatility
from .live_utils import atomic_json


class ProviderError(RuntimeError):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def provider_timestamp(value):
    """Tradier examples use both epoch seconds and milliseconds; accept either."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str) and not value.replace(".", "", 1).isdigit():
            stamp = pd.Timestamp(value)
            if stamp.tzinfo is None:
                return None
            return stamp.tz_convert("UTC").isoformat()
        epoch = float(value)
        if not np.isfinite(epoch) or epoch <= 0:
            return None
        return pd.Timestamp(epoch, unit="ms" if epoch > 1e11 else "s", tz="UTC").isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def objects(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class TradierProvider:
    BASE_URL = "https://api.tradier.com/v1/markets/"

    def __init__(self, config, cache_dir, session=None):
        token = os.environ.get("TRADIER_TOKEN", "").strip()
        if not token:
            raise ProviderError("TRADIER_TOKEN is missing. Set your production market-data token locally.")
        self.config = config
        self.cache = Path(cache_dir)
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": "Bearer "+token, "Accept": "application/json"})
        self.last_request = 0.0

    def get(self, endpoint, **params):
        # Limit this process to <= 30 requests/minute, below documented common limits.
        delay = 2.0-(time.monotonic()-self.last_request)
        if delay > 0:
            time.sleep(delay)
        self.last_request = time.monotonic()
        try:
            response = self.session.get(self.BASE_URL+endpoint, params=params,
                                        timeout=self.config.request_timeout_seconds, allow_redirects=False)
        except requests.RequestException as exc:
            raise ProviderError(f"Tradier network failure: {type(exc).__name__}") from None
        if response.status_code == 429:
            try:
                retry = max(60, float(response.headers.get("Retry-After", 60)))
            except ValueError:
                retry = 60
            raise ProviderError("Tradier HTTP 429; collection will back off.", retry_after=retry)
        if response.status_code in (401, 403):
            raise ProviderError(f"Tradier HTTP {response.status_code}; verify the production token and data entitlement.")
        if response.status_code != 200:
            raise ProviderError(f"Tradier HTTP {response.status_code} at {endpoint}")
        try:
            body = response.json()
        except ValueError:
            raise ProviderError("Tradier returned invalid JSON") from None
        if not isinstance(body, dict) or body.get("errors"):
            raise ProviderError(f"Tradier API error at {endpoint}")
        return body

    def history(self, symbol, now):
        day = now.tz_convert("America/New_York").date()
        path = self.cache/f"tradier-{symbol}-{day}-history.json"
        if path.exists():
            records = json.loads(path.read_text())
        else:
            start = (pd.Timestamp(day)-pd.Timedelta(days=max(180, 3*self.config.history_window))).date()
            end = (pd.Timestamp(day)-pd.Timedelta(days=1)).date()
            response = self.get("history", symbol=symbol, interval="daily", start=str(start), end=str(end))
            records = objects((response.get("history") or {}).get("day"))
            if not records:
                raise ProviderError(f"No daily history for {symbol}")
            atomic_json(path, records)
        history = pd.DataFrame(records)
        history["date"] = pd.to_datetime(history["date"], errors="raise")
        history = history.loc[history.date.dt.date < day].sort_values("date").drop_duplicates("date")
        if self.config.volatility is None:
            bars = history[[c for c in ("open", "high", "low", "close") if c in history]]
            try:
                estimate = realized_volatility(bars, self.config.baseline_estimator, self.config.history_window)
            except ValueError as exc:
                raise ProviderError(f"Baseline volatility unavailable for {symbol}: {exc}") from None
            sigma = estimate.sigma
            source = f"tradier_prior_{self.config.history_window}_session_realized_{estimate.estimator}"
        else:
            sigma, source = self.config.volatility, "user_fixed"
        if not np.isfinite(sigma) or sigma <= 0:
            raise ProviderError(f"Invalid realized volatility for {symbol}")
        history["symbol"] = symbol
        return history, sigma, source

    def fetch(self):
        frames, histories, failures, assumptions = [], [], [], {}
        started = pd.Timestamp.now(tz="UTC")
        retry_after = 0
        for symbol in self.config.tickers:
            try:
                history, sigma, source = self.history(symbol, started)
                histories.append(history)
                response = self.get("options/expirations", symbol=symbol, includeAllRoots="false")
                dates = objects((response.get("expirations") or {}).get("date"))
                dates = sorted(str(date) for date in dates if self.config.min_days <=
                               (pd.Timestamp(date).date()-started.tz_convert("America/New_York").date()).days <= self.config.max_days)
                if not dates:
                    raise ProviderError(f"No expirations in the configured maturity range for {symbol}")
                assumptions[symbol] = dict(baseline_sigma=sigma, baseline_source=source,
                                           history_end=str(history.date.max()), r=self.config.rate,
                                           q=self.config.dividend_yields[symbol])
                for expiration in dates[:self.config.expirations]:
                    chain = self.get("options/chains", symbol=symbol, expiration=expiration, greeks="true")
                    # Fetch spot immediately after each chain; preserve quote timestamps on both sides.
                    spot_response = self.get("quotes", symbols=symbol, greeks="false")
                    spot_quotes = objects((spot_response.get("quotes") or {}).get("quote"))
                    if not spot_quotes:
                        raise ProviderError(f"Missing underlying quote for {symbol}")
                    spot_quote = spot_quotes[0]
                    spot = float(spot_quote.get("last") or 0)
                    if not np.isfinite(spot) or spot <= 0:
                        raise ProviderError(f"Invalid spot for {symbol}")
                    spot_time = provider_timestamp(spot_quote.get("trade_date"))
                    as_of = pd.Timestamp.now(tz="UTC").isoformat()
                    rows = []
                    for quote in objects((chain.get("options") or {}).get("option")):
                        greeks = quote.get("greeks") or {}
                        rows.append({**quote, "contractSymbol": quote.get("symbol"), "symbol": symbol,
                                     "option_type": quote.get("option_type"), "expiration": expiration,
                                     "as_of": as_of, "spot": spot, "spot_timestamp": spot_time,
                                     "spot_source": "tradier_underlying_last", "bid_timestamp": provider_timestamp(quote.get("bid_date")),
                                     "ask_timestamp": provider_timestamp(quote.get("ask_date")),
                                     "lastTradeDate": provider_timestamp(quote.get("trade_date")),
                                     "lastPrice": quote.get("last"), "openInterest": quote.get("open_interest"),
                                     "impliedVolatility": greeks.get("mid_iv"), "r": self.config.rate,
                                     "q": self.config.dividend_yields[symbol], "baseline_sigma": sigma,
                                     "baseline_source": source, "exercise_style": "american", "data_kind": "market",
                                     "provider": "tradier", "feed": "production", "expiry_hour": 16})
                    if not rows:
                        failures.append(dict(symbol=symbol, expiration=expiration, error="Empty options chain"))
                    else:
                        frames.append(pd.DataFrame(rows))
            except (ProviderError, KeyError, ValueError, TypeError) as exc:
                failures.append(dict(symbol=symbol, error=str(exc)))
                retry_after = max(retry_after, getattr(exc, "retry_after", 0))
                # Stop after throttling/auth failure; do not amplify provider failures across assets.
                if getattr(exc, "retry_after", 0) or "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                    break
        meta = dict(data_kind="market", provider="tradier", feed="production", assumptions=assumptions,
                    acquisition_started=started.isoformat(), acquisition_finished=pd.Timestamp.now(tz="UTC").isoformat(),
                    requested_tickers=list(self.config.tickers), failures=failures, retry_after_seconds=retry_after,
                    quote_timestamp_available=True, config=self.config.public_dict(),
                    notes=["Quote freshness is checked per row. Production endpoint entitlement depends on your account.",
                           "Prior daily close volatility uses provider history; no independent corporate-action repair is applied."])
        return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), meta,
                pd.concat(histories, ignore_index=True) if histories else pd.DataFrame())


def acquire(config, cache_dir):
    if config.provider == "tradier":
        return TradierProvider(config, cache_dir).fetch()
    raw, meta, history = fetch_options(config.tickers, config.rate, config.dividend_yields,
                                       config.expirations, config.volatility, config.history_window,
                                       estimator=config.baseline_estimator)
    if not raw.empty:
        raw["provider"] = "yahoo"
        raw["feed"] = "unverified_quote_timestamps"
        raw["bid_timestamp"] = None
        raw["ask_timestamp"] = None
    meta.update(provider="yahoo", config=config.public_dict(),
                retry_after_seconds=3600 if any("limit" in str(error).lower() for error in meta.get("failures", [])) else 0)
    return raw, meta, history
