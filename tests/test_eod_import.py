"""Fixture CSVs stand in for the DoltHub export; nothing here touches the network."""
import numpy as np
import pandas as pd
import pytest
from options_engine import BlackScholesEngine
from options_engine.data import write_snapshot
from options_engine.eod_import import build_session_snapshots, import_eod, load_chain_csv, load_underlying_csv
from options_engine.live_config import LiveConfig
from options_engine.store import ObservationStore, training_quality


def eod_config(**overrides):
    settings = dict(provider="dolt_eod", training_tier="daily_eod", min_open_interest=0,
                    tickers=("TEST",), dividend_yields={"TEST": .01}, history_window=60)
    settings.update(overrides)
    return LiveConfig(**settings)


def fixture_csvs(tmp_path, sessions=3, sigma=.2):
    import exchange_calendars as xc
    calendar = xc.get_calendar("XNYS")
    days = [str(d.date()) for d in calendar.sessions_in_range("2023-01-01", "2023-06-30")]
    chain_days = days[70:70+sessions]
    rng = np.random.default_rng(11)
    closes = 100*np.exp(np.cumsum(rng.normal(0, sigma/np.sqrt(252), len(days))))
    underlying = pd.DataFrame(dict(date=days[:70+sessions], act_symbol="TEST",
                                   open=closes[:70+sessions]*.999, high=closes[:70+sessions]*1.01,
                                   low=closes[:70+sessions]*.99, close=closes[:70+sessions]))
    rows = []
    for i, day in enumerate(chain_days):
        spot = closes[70+i]
        expiration = days[70+sessions+20]
        T = (pd.Timestamp(expiration)-pd.Timestamp(day)).days/365
        for strike in np.round(np.linspace(spot*.9, spot*1.1, 9), 0):
            m = np.log(spot/strike)
            iv = sigma*np.exp(.1+.3*m+.5*m*m)
            for kind in ("Call", "Put"):
                mid = BlackScholesEngine(spot, strike, T, .04, iv, .01).price(kind.lower())
                rows.append(dict(date=day, act_symbol="TEST", expiration=expiration, strike=strike,
                                 call_put=kind, bid=round(mid*.99, 4), ask=round(mid*1.01, 4), vol=round(iv, 4)))
    chain = pd.DataFrame(rows)
    chain_path, underlying_path = tmp_path/"chain.csv", tmp_path/"underlying.csv"
    chain.to_csv(chain_path, index=False)
    underlying.to_csv(underlying_path, index=False)
    return chain_path, underlying_path, chain_days


def test_loaders_normalize_and_validate(tmp_path):
    chain_path, underlying_path, _ = fixture_csvs(tmp_path)
    chain = load_chain_csv(chain_path)
    assert set(chain.option_type.unique()) == {"call", "put"}
    assert "call_put" not in chain
    underlying = load_underlying_csv(underlying_path)
    assert list(underlying.columns) == ["date", "symbol", "open", "high", "low", "close"]
    broken = pd.read_csv(chain_path).drop(columns=["bid"])
    broken.to_csv(tmp_path/"broken.csv", index=False)
    with pytest.raises(ValueError, match="bid"):
        load_chain_csv(tmp_path/"broken.csv")


def test_snapshots_are_close_stamped_and_leak_free(tmp_path):
    chain_path, underlying_path, chain_days = fixture_csvs(tmp_path)
    config = eod_config()
    chain, underlying = load_chain_csv(chain_path), load_underlying_csv(underlying_path)
    snapshots = {day: raw for day, raw, _ in build_session_snapshots(chain, underlying, config)}
    assert list(snapshots) == chain_days
    first = snapshots[chain_days[0]]
    import exchange_calendars as xc
    close = pd.Timestamp(xc.get_calendar("XNYS").session_close(chain_days[0])).tz_convert("UTC").isoformat()
    assert set(first.as_of.unique()) == {close}
    assert set(first.bid_timestamp.unique()) == {close} and set(first.spot_timestamp.unique()) == {close}
    assert (first.provider == "dolt_eod").all() and (first.feed == "historical_eod").all()
    assert first.contractSymbol.str.match(r"TEST\d{6}[CP]\d{8}").all()
    # Changing sessions at or after a chain day must not change that day's baseline.
    tampered = underlying.copy()
    tampered.loc[tampered.date >= chain_days[0], ["open", "high", "low", "close"]] *= 3
    tampered_first = next(raw for day, raw, _ in build_session_snapshots(chain, tampered, config) if day == chain_days[0])
    assert tampered_first.baseline_sigma.iloc[0] == first.baseline_sigma.iloc[0]
    # Insufficient history skips the session with a recorded reason instead of guessing.
    short = underlying.tail(30).reset_index(drop=True)
    day, raw, metadata = next(iter(build_session_snapshots(chain, short, config)))
    assert raw.empty and "baseline_unavailable" in metadata["failures"][0]["reason"]


def test_import_ingests_dedups_and_marks_training_eligible(tmp_path):
    chain_path, underlying_path, chain_days = fixture_csvs(tmp_path)
    config = eod_config()
    root = tmp_path/"live"
    summary = import_eod(chain_path, underlying_path, config, root)
    assert summary["sessions_imported"] == len(chain_days)
    assert summary["training_rows"] > 0 and summary["inserted_rows"] >= summary["training_rows"]
    again = import_eod(chain_path, underlying_path, config, root)
    assert again["duplicate_sessions"] == len(chain_days) and again["inserted_rows"] == 0
    status = ObservationStore(root).status()
    assert status["training_sessions"] == len(chain_days)
    with pytest.raises(ValueError, match="daily_eod"):
        import_eod(chain_path, underlying_path, LiveConfig(), root)


def test_tiers_are_mutually_exclusive(tmp_path):
    from tests.test_live import fixture_quotes
    tradier_folder = write_snapshot(fixture_quotes(), tmp_path/"tradier_snapshot",
                                    {"provider": "tradier", "data_kind": "market"})
    eod_store = ObservationStore(tmp_path/"eod_live")
    result = eod_store.ingest(tradier_folder, eod_config(tickers=("TEST",)))
    assert result["inserted_rows"] > 0 and result["training_rows"] == 0
    reasons = eod_store.export(include_excluded=True).quality_reasons
    assert reasons.str.contains("wrong_feed_for_daily_eod_tier").all()
    chain_path, underlying_path, _ = fixture_csvs(tmp_path)
    import_eod(chain_path, underlying_path, eod_config(), tmp_path/"eod_live2")
    strict_store = ObservationStore(tmp_path/"strict_live")
    eod_snapshot = next((tmp_path/"eod_live2"/"snapshots").glob("*/*/metadata.json")).parent
    strict = strict_store.ingest(eod_snapshot, LiveConfig(tickers=("TEST",), dividend_yields={"TEST": .01}))
    assert strict["training_rows"] == 0


def test_eod_rows_state_their_exclusion_reasons(tmp_path):
    chain_path, underlying_path, chain_days = fixture_csvs(tmp_path)
    config = eod_config()
    chain, underlying = load_chain_csv(chain_path), load_underlying_csv(underlying_path)
    _, raw, _ = next(iter(build_session_snapshots(chain, underlying, config)))
    row = raw.iloc[0].to_dict()
    row.update(mid=5.0, days_to_expiry=30, log_moneyness=.01, iv_brent_converged=True,
               iv_brent_poorly_identified=False, iv_brent_volatility=.2)
    assert training_quality(row, config) == []
    stale = dict(row, spot_timestamp=str(pd.Timestamp(row["as_of"])-pd.Timedelta(hours=3)))
    assert "implied_spot_timestamp_mismatch" in training_quality(stale, config)
    weekend = dict(row, as_of="2023-04-15T20:00:00+00:00", bid_timestamp="2023-04-15T20:00:00+00:00",
                   ask_timestamp="2023-04-15T20:00:00+00:00", spot_timestamp="2023-04-15T20:00:00+00:00")
    assert "not_a_session_close" in training_quality(weekend, config)
