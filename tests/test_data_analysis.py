import sys
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from options_engine.data import time_to_expiry, filter_options, FilterConfig, write_snapshot, read_snapshot, fetch_options
from options_engine.demo import synthetic_snapshot
from options_engine.analysis import analyze_options, metrics, write_report, market_parity_diagnostics


def one_quote():
    raw, _ = synthetic_snapshot()
    return raw.loc[(raw.symbol == "DEMO_A") & (raw.strike == 100) & (raw.option_type == "call")].head(1).copy()


def test_fractional_expiry_dst_and_naive_rejection():
    assert time_to_expiry("2026-09-18","2026-09-18T19:00:00Z") == pytest.approx(1/(24*365))
    assert time_to_expiry("2026-12-18","2026-12-18T20:00:00Z") == pytest.approx(1/(24*365))
    assert time_to_expiry("2026-09-18","2026-09-18T20:00:00Z") == 0
    assert time_to_expiry("2026-09-18","2026-09-18T21:00:00Z") < 0
    with pytest.raises(ValueError):
        time_to_expiry("2026-09-18","2026-09-18 19:00:00")


@pytest.mark.parametrize("changes,reason", [
    ({"bid":0},"invalid_quote"),({"bid":5,"ask":4},"crossed_market"),
    ({"expiration":"2020-01-01"},"expired"),({"as_of":"garbage"},"invalid_timestamp"),
    ({"volume":-1},"invalid_volume"),({"openInterest":np.nan},"low_or_missing_open_interest"),
    ({"ask":100},"wide_spread"),({"spot":0},"invalid_spot"),({"r":np.nan},"invalid_r")])
def test_quote_rejection_reasons(changes,reason):
    raw = one_quote()
    for key,value in changes.items():
        raw[key] = value
    result,audit = filter_options(raw)
    assert result.empty
    assert reason in audit.iloc[0].filter_reasons


def test_missing_volume_is_optional_and_duplicates_all_excluded():
    raw = one_quote().drop(columns="volume")
    assert len(filter_options(raw)[0]) == 1
    assert filter_options(raw, FilterConfig(min_volume=1))[0].empty
    duplicates = pd.concat([raw,raw],ignore_index=True)
    result,audit = filter_options(duplicates)
    assert result.empty
    assert audit.filter_reasons.str.contains("duplicate_contract_snapshot").all()


def test_trade_age_is_explicit_filter_not_quote_age():
    raw=one_quote()
    raw["lastTradeDate"]="2026-01-01T00:00:00Z"
    assert len(filter_options(raw)[0]) == 1
    assert filter_options(raw,FilterConfig(max_last_trade_age_days=1))[0].empty


def test_snapshot_checksum_and_replay(tmp_path):
    raw,meta=synthetic_snapshot()
    folder=write_snapshot(raw,tmp_path/"snapshot",meta)
    replay,loaded=read_snapshot(folder)
    assert len(replay)==len(raw) and loaded["data_kind"]=="synthetic"
    before,_=analyze_options(raw.head(20))
    after,_=analyze_options(replay.head(20))
    np.testing.assert_allclose(before.baseline_price,after.baseline_price,rtol=0,atol=1e-13)
    with open(folder/"raw_options.csv","a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError,match="checksum"):
        read_snapshot(folder)


def test_iv_failures_are_not_removed_from_baseline_metrics():
    raw=one_quote()
    raw["bid"]=101.0
    raw["ask"]=102.0
    result,_=analyze_options(raw)
    assert len(result)==1
    assert result.iloc[0].iv_brent_status=="outside_european_bounds"
    assert metrics(result)["n"]==1
    assert np.isfinite(result.iloc[0].baseline_price)


def test_baseline_does_not_use_provider_or_fitted_iv():
    raw=one_quote()
    first,_=analyze_options(raw)
    raw["impliedVolatility"]=4.0
    raw["bid"]*=1.2
    raw["ask"]*=1.2
    second,_=analyze_options(raw)
    assert first.iloc[0].baseline_price==second.iloc[0].baseline_price
    assert second.iloc[0].iv_brent_volatility>first.iloc[0].iv_brent_volatility


def test_percentage_denominator_and_empty_report(tmp_path):
    frame=pd.DataFrame(dict(mid=[.01,1.0],error=[.01,-.5],baseline_within_spread=[False,True]))
    result=metrics(frame,.1)
    assert result["n"]==2 and result["n_mape"]==1
    assert result["mape_pct"]==50
    assert result["mae"]==.255
    raw=one_quote()
    raw["bid"]=0
    result,audit=analyze_options(raw)
    write_report(result,audit,{"data_kind":"synthetic"},tmp_path)
    assert "No usable quotes remain" in (tmp_path/"REPORT.md").read_text()


def test_market_parity_interval():
    raw,_=synthetic_snapshot()
    result,_=analyze_options(raw.loc[(raw.symbol=="DEMO_A") & raw.strike.between(95,105)])
    parity=market_parity_diagnostics(result)
    assert len(parity)>0
    assert parity.theory_inside_interval.all()


def test_fetch_provider_metadata_and_partial_failure(monkeypatch):
    idx=pd.date_range(end=pd.Timestamp.now(tz="UTC")-pd.Timedelta(days=2),periods=90,freq="B")
    hist=pd.DataFrame({"Close":np.linspace(95,105,90),"Adj Close":np.linspace(94,104,90)},index=idx)
    quote=one_quote()[["bid","ask","strike","volume","openInterest","impliedVolatility"]]
    class FakeTicker:
        options=["2027-01-15","2027-02-19"]
        def history(self,**kwargs):
            assert kwargs["auto_adjust"] is False
            return hist
        def option_chain(self,expiry):
            if expiry.endswith("02-19"):
                raise RuntimeError("provider unavailable")
            return SimpleNamespace(calls=quote,puts=quote,underlying={"regularMarketPrice":110,"regularMarketTime":1790000000})
    monkeypatch.setitem(sys.modules,"yfinance",SimpleNamespace(Ticker=lambda symbol:FakeTicker()))
    raw,meta,history=fetch_options(["TEST"],.04,{"TEST":.01},expirations=2)
    assert len(raw)==2 and len(history)==90
    assert raw.spot.eq(110).all()
    assert raw.exercise_style.eq("american").all()
    assert raw.baseline_sigma.gt(0).all()
    assert len(meta["failures"])==1
    assert meta["quote_timestamp_available"] is False
