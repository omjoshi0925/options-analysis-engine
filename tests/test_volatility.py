"""Simulated bars only; nothing here is market evidence."""
import sys
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from options_engine import ESTIMATORS, realized_volatility
from options_engine.data import fetch_options
from options_engine.live_config import LiveConfig
from options_engine.providers import TradierProvider


def simulated_bars(sigma_intraday, sigma_overnight=0.0, days=250, steps=390, seed=7):
    rng = np.random.default_rng(seed)
    dt = 1/(252*steps)
    increments = sigma_intraday*np.sqrt(dt)*rng.standard_normal((days, steps))-0.5*sigma_intraday**2*dt
    gaps = sigma_overnight*np.sqrt(1/252)*rng.standard_normal(days)
    rows, level = [], 0.0
    for day in range(days):
        level += gaps[day]
        path = level+np.cumsum(increments[day])
        rows.append(dict(open=np.exp(level), high=np.exp(max(level, path.max())), low=np.exp(min(level, path.min())), close=np.exp(path[-1])))
        level = path[-1]
    return pd.DataFrame(rows)


def test_close_to_close_reproduces_previous_formula():
    closes = pd.Series(np.exp(np.cumsum(np.random.default_rng(3).normal(0, .01, 80))))
    expected = float(np.log(closes).diff().dropna().tail(60).std(ddof=1)*np.sqrt(252))
    estimate = realized_volatility(pd.DataFrame({"Close": closes}), "close_to_close", 60)
    assert estimate.sigma == pytest.approx(expected, rel=1e-12)
    assert estimate.observations == 61 and estimate.window == 60 and estimate.clamped_bars == 0


@pytest.mark.parametrize("estimator", ESTIMATORS)
def test_every_estimator_recovers_simulated_volatility(estimator):
    bars = simulated_bars(.25)
    estimate = realized_volatility(bars, estimator, 240)
    assert estimate.sigma == pytest.approx(.25, rel=.12), estimator
    assert estimate.estimator == estimator


def test_yang_zhang_includes_overnight_variance_and_parkinson_does_not():
    bars = simulated_bars(.25, sigma_overnight=.20)
    total = np.hypot(.25, .20)
    yang_zhang = realized_volatility(bars, "yang_zhang", 240).sigma
    parkinson = realized_volatility(bars, "parkinson", 240).sigma
    assert yang_zhang == pytest.approx(total, rel=.12)
    assert parkinson == pytest.approx(.25, rel=.12)
    assert yang_zhang > 1.15*parkinson
    assert realized_volatility(bars, "close_to_close", 240).sigma == pytest.approx(total, rel=.12)


def test_inconsistent_bars_are_clamped_and_counted():
    bars = simulated_bars(.3, days=40)
    bars.loc[35, "high"] = bars.loc[35, "close"]*0.99  # inside the 30-bar window that is analysed
    estimate = realized_volatility(bars, "garman_klass", 30)
    assert estimate.clamped_bars == 1 and np.isfinite(estimate.sigma) and estimate.sigma > 0


@pytest.mark.parametrize("estimator,frame,window,message", [
    ("bogus", pd.DataFrame({"close": [1, 2, 3]}), 2, "estimator must be"),
    ("parkinson", pd.DataFrame({"close": [1, 2, 3]}), 2, "needs daily"),
    ("close_to_close", pd.DataFrame({"close": [1, 2, 3]}), 5, "Need 6 complete"),
    ("close_to_close", pd.DataFrame({"close": [1, -2, 3]}), 2, "Nonpositive"),
    ("close_to_close", pd.DataFrame({"close": [1, 1, 1]}), 2, "Invalid realized"),
    ("close_to_close", pd.DataFrame({"close": [1, 2, 3]}), 1, "window must be"),
])
def test_estimator_validation(estimator, frame, window, message):
    with pytest.raises(ValueError, match=message):
        realized_volatility(frame, estimator, window)


def test_live_config_validates_estimator():
    assert LiveConfig().baseline_estimator == "close_to_close"
    assert LiveConfig(baseline_estimator="yang_zhang").public_dict()["baseline_estimator"] == "yang_zhang"
    with pytest.raises(ValueError, match="baseline_estimator"):
        LiveConfig(baseline_estimator="close")


def test_tradier_history_uses_configured_estimator(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADIER_TOKEN", "fixture-token")
    monkeypatch.setattr("options_engine.providers.time.sleep", lambda seconds: None)
    now = pd.Timestamp.now(tz="UTC")
    dates = pd.bdate_range(end=now.tz_localize(None)-pd.Timedelta(days=2), periods=70)
    bars = simulated_bars(.3, days=70, seed=11)
    history = [dict(date=str(date.date()), **{k: float(bars.loc[i, k]) for k in ("open", "high", "low", "close")}) for i, date in enumerate(dates)]
    class Session:
        headers = {}
        def get(self, url, params, timeout, allow_redirects):
            return SimpleNamespace(status_code=200, json=lambda: {"history": {"day": history}}, headers={})
    provider = TradierProvider(LiveConfig(tickers=("TEST",), dividend_yields={"TEST": .01}, baseline_estimator="parkinson"), tmp_path, Session())
    _, sigma, source = provider.history("TEST", now)
    assert 0 < sigma < 1 and source.endswith("_parkinson")
    closes_only = [dict(date=row["date"], close=row["close"]) for row in history]
    class ClosesSession(Session):
        def get(self, *args, **kwargs):
            return SimpleNamespace(status_code=200, json=lambda: {"history": {"day": closes_only}}, headers={})
    provider = TradierProvider(LiveConfig(tickers=("OTHER",), dividend_yields={"OTHER": .01}, baseline_estimator="parkinson"), tmp_path, ClosesSession())
    with pytest.raises(Exception, match="needs daily"):
        provider.history("OTHER", now)


def test_yahoo_fetch_range_estimator_and_missing_columns(monkeypatch):
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC")-pd.Timedelta(days=2), periods=90, freq="B")
    bars = simulated_bars(.3, days=90, seed=5)
    hist = pd.DataFrame({"Open": bars.open.to_numpy()*100, "High": bars.high.to_numpy()*100, "Low": bars.low.to_numpy()*100,
                         "Close": bars.close.to_numpy()*100, "Adj Close": bars.close.to_numpy()*99}, index=idx)
    quote = pd.DataFrame(dict(bid=[1.0], ask=[1.1], strike=[100.0], volume=[10], openInterest=[100], impliedVolatility=[.3]))
    class FakeTicker:
        options = ["2027-01-15"]
        def __init__(self, frame):
            self.frame = frame
        def history(self, **kwargs):
            return self.frame
        def option_chain(self, expiry):
            return SimpleNamespace(calls=quote, puts=quote, underlying={"regularMarketPrice": 100})
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda symbol: FakeTicker(hist)))
    raw, meta, _ = fetch_options(["TEST"], .04, {"TEST": .01}, expirations=1, estimator="garman_klass")
    assert len(raw) == 2 and raw.baseline_sigma.gt(0).all()
    assert meta["assumptions"]["TEST"]["baseline_source"] == "realized_60_sessions_garman_klass_unadjusted OHLC"
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda symbol: FakeTicker(hist[["Close", "Adj Close"]])))
    raw, meta, _ = fetch_options(["TEST"], .04, {"TEST": .01}, expirations=1, estimator="garman_klass")
    assert raw.empty and "needs daily" in meta["failures"][0]["error"]
    with pytest.raises(ValueError, match="estimator"):
        fetch_options(["TEST"], .04, {"TEST": .01}, estimator="typo")
