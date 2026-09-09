"""Dated rate and dividend inputs: alignment, window boundaries, share basis, and config forms."""
import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from options_engine import BlackScholesEngine
from options_engine.analysis import analyze_options
from options_engine.carry_inputs import (CarryInputs, DividendSeries, InputUnavailable, RateSeries, apply_carry,
                                         effective_carry)
from options_engine.data import time_to_expiry
from options_engine.learning import basis, evaluate
from options_engine.live_config import LiveConfig

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT/"data"/"external"


def write_fred(path, rows):
    path.write_text("observation_date,DGS3MO\n"+"".join(f"{d},{v}\n" for d, v in rows))
    return path


def test_rate_is_strictly_prior_percent_converted_and_skips_dots(tmp_path):
    series = RateSeries.from_csv(write_fred(tmp_path/"r.csv", [("2024-01-02", "5.0"), ("2024-01-03", "."), ("2024-01-04", "5.5"), ("2024-01-05", "")]))
    assert series.dates == [dt.date(2024, 1, 2), dt.date(2024, 1, 4)]
    # On a FRED date itself the quote of that day is not yet known: the prior quote applies.
    assert series.rate_for("2024-01-04") == pytest.approx(math.log1p(.05))
    assert series.quote_before("2024-01-04")[0] == dt.date(2024, 1, 2)
    assert series.rate_for("2024-01-05") == pytest.approx(math.log1p(.055))
    assert series.rate_for(dt.date(2024, 1, 14)) == pytest.approx(math.log1p(.055))      # 10 days after the last quote: still fresh
    with pytest.raises(InputUnavailable) as failure:
        series.rate_for("2024-01-02")
    assert failure.value.reason == "rate_unavailable"
    with pytest.raises(InputUnavailable) as stale:
        series.rate_for(dt.date(2024, 1, 15))                                              # 11 days: stale
    assert stale.value.reason == "rate_stale"
    decimal = RateSeries.from_csv(write_fred(tmp_path/"d.csv", [("2024-01-02", "0.05")]), units="decimal")
    assert decimal.rate_for("2024-01-03") == pytest.approx(math.log1p(.05))
    (tmp_path/"wide.csv").write_text("observation_date,DGS1MO,DGS3MO\n2024-01-02,4.0,5.0\n")
    assert RateSeries.from_csv(tmp_path/"wide.csv", column="DGS3MO").rate_for("2024-01-03") == pytest.approx(math.log1p(.05))
    with pytest.raises(ValueError, match="Invalid rate quote"):
        RateSeries.from_csv(write_fred(tmp_path/"bad.csv", [("2024-01-02", "-150")]))
    with pytest.raises(ValueError, match="duplicate"):
        RateSeries(["2024-01-02", "2024-01-02"], [.01, .02])


def test_committed_dgs3mo_holiday_alignment():
    """A blank Thanksgiving row and a Friday session: the rate is the last quoted business day."""
    rows = {row.split(",")[0]: row.split(",")[1] for row in (EXTERNAL/"raw"/"DGS3MO.csv").read_text().splitlines()[1:]}
    assert rows["2023-11-23"] == ""                       # missing days are blank in this download
    series = RateSeries.from_csv(EXTERNAL/"raw"/"DGS3MO.csv")
    quote_date, rate = series.quote_before("2023-11-24")
    assert quote_date == dt.date(2023, 11, 22) and rate == pytest.approx(math.log1p(float(rows["2023-11-22"])/100))
    assert series.quote_before("2020-08-31")[0] == dt.date(2020, 8, 28)


def bars_frame(symbol, start, end, close=100.0):
    days = pd.date_range(start, end, freq="D")
    return pd.DataFrame(dict(symbol=symbol, date=[d.date() for d in days], close=close))


def test_dividend_window_includes_t_minus_1_and_t_minus_365_only():
    t = dt.date(2023, 6, 15)
    dividends = pd.DataFrame(dict(symbol="X", ex_date=[t-dt.timedelta(days=366), t-dt.timedelta(days=365), t-dt.timedelta(days=1), t],
                                  amount=[1.0, 2.0, 4.0, 8.0]))
    series = DividendSeries(dividends, bars_frame("X", "2021-01-01", "2024-01-01", 100.0), stale_days=400)
    q, details = series.yield_for("X", t)
    assert q == pytest.approx((2.0+4.0)/100.0)
    assert details["distributions"] == 2 and details["window_start"] == t-dt.timedelta(days=365) and details["window_end"] == t-dt.timedelta(days=1)
    assert details["bar_date"] == t-dt.timedelta(days=1)


def test_rebasing_applies_only_to_pre_split_ex_dates_when_prior_bar_is_post_split():
    dividends = pd.DataFrame(dict(symbol=["X", "X", "SPY", "SPY"], ex_date=["2020-08-07", "2020-11-06"]*2, amount=[.8, .2, .8, .2]))
    splits = pd.DataFrame(dict(symbol=["X"], ex_date=["2020-08-31"], to_factor=[2], for_factor=[1]))
    bars = pd.concat([bars_frame("X", "2020-01-01", "2020-08-30", 400.0), bars_frame("X", "2020-08-31", "2021-06-30", 100.0),
                      bars_frame("SPY", "2020-01-01", "2021-06-30", 100.0)])
    series = DividendSeries(dividends, bars, splits, stale_days=400, history_start="2019-01-01")
    assert series.yield_for("X", "2020-08-31")[0] == pytest.approx(.8/400)        # prior bar is pre-split: declared amount
    assert series.yield_for("X", "2020-09-01")[0] == pytest.approx(.8/2/100)      # prior bar IS the split date: already rebased
    assert series.yield_for("X", "2020-09-02")[0] == pytest.approx(.8/2/100)      # prior bar is post-split: pre-split dividend halved
    assert series.yield_for("X", "2020-12-02")[0] == pytest.approx((.8/2+.2)/100)  # post-split ex-date untouched
    assert series.yield_for("SPY", "2020-09-02")[0] == pytest.approx(.8/100)      # no split rows: never rebased
    assert series.yield_for("SPY", "2020-12-02")[0] == pytest.approx((.8+.2)/100)
    # An ex-date on the split date is already on the new basis; two splits compound.
    dividends = pd.DataFrame(dict(symbol="Y", ex_date=["2020-08-07", "2020-08-31", "2020-11-06"], amount=[.8, .3, .2]))
    splits = pd.DataFrame(dict(symbol=["Y", "Y"], ex_date=["2020-08-31", "2020-10-01"], to_factor=[2, 3], for_factor=[1, 1]))
    twice = DividendSeries(dividends, bars_frame("Y", "2020-01-01", "2021-06-30", 100.0), splits, stale_days=400, history_start="2019-01-01")
    assert twice.yield_for("Y", "2020-09-02")[0] == pytest.approx((.8/2+.3)/100)
    assert twice.yield_for("Y", "2020-12-02")[0] == pytest.approx((.8/6+.3/3+.2)/100)


def committed_series():
    return DividendSeries.from_csv(EXTERNAL/"dividends.csv", EXTERNAL/"raw"/"full_underlying.csv", EXTERNAL/"splits.csv")


def test_pinned_aapl_examples_against_committed_inputs():
    series = committed_series()
    bars = pd.read_csv(EXTERNAL/"raw"/"full_underlying.csv")
    close = {row.date: row.close for row in bars.loc[bars.act_symbol == "AAPL"].itertuples()}
    assert close["2020-08-28"] == pytest.approx(499.23) and close["2020-08-31"] == pytest.approx(129.04)
    q_pre, pre = series.yield_for("AAPL", "2020-08-31")           # t-1 = 2020-08-28, before the split
    assert pre["bar_date"] == dt.date(2020, 8, 28) and pre["close"] == pytest.approx(499.23)
    assert pre["declared_sum"] == pytest.approx(3.18) and q_pre == pytest.approx(3.18/499.23)
    q_post, post = series.yield_for("AAPL", "2020-09-02")         # t-1 = 2020-09-01, after the split
    assert post["bar_date"] == dt.date(2020, 9, 1) and post["close"] == pytest.approx(close["2020-09-01"])
    assert post["rebased_sum"] == pytest.approx(.795) and q_post == pytest.approx(.795/close["2020-09-01"])
    q_split, on_split = series.yield_for("AAPL", "2020-09-01")    # t-1 = 2020-08-31, the first split-adjusted bar
    assert on_split["bar_date"] == dt.date(2020, 8, 31) and q_split == pytest.approx(.795/129.04)
    dividends = pd.read_csv(EXTERNAL/"dividends.csv")
    spy = dividends.loc[(dividends.symbol == "SPY") & (dividends.ex_date >= "2019-09-03") & (dividends.ex_date <= "2020-09-01")]
    q_spy, spy_details = series.yield_for("SPY", "2020-09-02")
    assert spy_details["rebased_sum"] == pytest.approx(spy.amount.sum()) and q_spy == pytest.approx(spy.amount.sum()/spy_details["close"])


def test_unavailable_inputs_carry_reasons():
    dividends = pd.DataFrame(dict(symbol=["X"], ex_date=["2022-03-01"], amount=[1.0]))
    series = DividendSeries(dividends, bars_frame("X", "2022-01-01", "2022-12-31"), stale_days=100)
    with pytest.raises(InputUnavailable) as early:
        series.yield_for("X", "2022-06-01")                       # window starts before the first known ex-date
    assert early.value.reason == "dividend_history_unavailable"
    with pytest.raises(InputUnavailable) as stale:
        series.yield_for("X", "2023-06-01")                       # window ends after history plus stale_days
    assert stale.value.reason == "dividend_history_stale"
    with pytest.raises(InputUnavailable) as unknown:
        series.yield_for("Y", "2022-06-01")
    assert unknown.value.reason == "dividend_history_unavailable"
    late = DividendSeries(pd.DataFrame(dict(symbol=["Z"], ex_date=["2020-01-01"], amount=[1.0])),
                          bars_frame("Z", "2021-06-01", "2021-12-31"), stale_days=1000)
    with pytest.raises(InputUnavailable) as no_bar:
        late.yield_for("Z", "2021-06-01")                         # no bar before the session
    assert no_bar.value.reason == "spot_prior_unavailable"
    with pytest.raises(InputUnavailable) as gap:
        late.yield_for("Z", "2022-02-01")                         # bars end 2021-12-31: more than max_bar_gap_days before
    assert gap.value.reason == "spot_prior_unavailable"


def test_history_coverage_boundaries_and_empty_windows():
    dividends = pd.DataFrame(dict(symbol=["X"], ex_date=["2022-03-01"], amount=[1.0]))
    bars = bars_frame("X", "2020-01-01", "2023-12-31", 50.0)
    series = DividendSeries(dividends, bars, history_start="2021-01-01", history_end="2022-12-31")
    t = dt.date(2022, 1, 1)                                       # window [2021-01-01, 2021-12-31]: exactly covered, no dividends
    q, details = series.yield_for("X", t)
    assert q == 0 and details["distributions"] == 0
    with pytest.raises(InputUnavailable) as early:
        series.yield_for("X", t-dt.timedelta(days=1))             # window starts one day before history_start
    assert early.value.reason == "dividend_history_unavailable"
    assert series.yield_for("X", dt.date(2023, 1, 1))[0] == pytest.approx(1.0/50)   # window ends exactly on history_end
    with pytest.raises(InputUnavailable) as stale:
        series.yield_for("X", dt.date(2023, 1, 2))
    assert stale.value.reason == "dividend_history_stale"
    inferred = DividendSeries(dividends, bars, stale_days=100, history_start="2021-01-01")   # no history_end: last ex-date + stale_days
    assert inferred.yield_for("X", dt.date(2022, 6, 10))[0] == pytest.approx(1.0/50)          # window end 2022-06-09 == last + 100
    with pytest.raises(InputUnavailable) as inferred_stale:
        inferred.yield_for("X", dt.date(2022, 6, 11))
    assert inferred_stale.value.reason == "dividend_history_stale"
    undeclared = DividendSeries(dividends, bars, stale_days=100)                              # no history_start: first ex-date
    with pytest.raises(InputUnavailable) as before_first:
        undeclared.yield_for("X", dt.date(2022, 6, 10))                                       # window starts 2021-06-10, before 2022-03-01
    assert before_first.value.reason == "dividend_history_unavailable"


def test_config_forms_flat_dict_and_series(tmp_path):
    flat = LiveConfig(tickers=("SPY",), rate=.03, dividend_yields={"SPY": .02})
    assert flat.rate_spec == dict(mode="constant", value=.03) and flat.dividend_spec == dict(mode="constant", yields={"SPY": .02})
    assert "dividend" not in flat.public_dict() and flat.public_dict()["rate"] == .03
    boxed = LiveConfig(tickers=("SPY",), rate={"mode": "constant", "value": .03}, dividend={"mode": "constant", "yields": {"SPY": .02}})
    assert boxed.public_dict() == flat.public_dict() and boxed.constant_rate == .03 and boxed.constant_dividend_yields == {"SPY": .02}
    series = LiveConfig(tickers=("SPY",), rate={"mode": "series", "path": "r.csv"},
                        dividend={"mode": "series", "path": "d.csv", "bars": "b.csv", "splits": "s.csv"})
    assert series.rate_spec["alignment"] == "strictly_prior" and series.dividend_spec["window_days"] == 365
    assert series.dividend_yields == {} and series.public_dict()["dividend"]["mode"] == "series"
    with pytest.raises(ValueError, match="constant rate"):
        _ = series.constant_rate
    with pytest.raises(ValueError, match="constant yields"):
        _ = series.constant_dividend_yields
    with pytest.raises(ValueError, match="mode"):
        LiveConfig(rate={"mode": "spline", "path": "r.csv"})
    with pytest.raises(ValueError, match="strictly_prior"):
        LiveConfig(rate={"mode": "series", "path": "r.csv", "alignment": "same_day"})
    with pytest.raises(ValueError, match="bars"):
        LiveConfig(dividend={"mode": "series", "path": "d.csv"})
    with pytest.raises(ValueError, match="yield required"):
        LiveConfig(tickers=("SPY",), dividend={"mode": "constant", "yields": {}})
    with pytest.raises(ValueError, match="Unknown constant rate keys"):
        LiveConfig(rate={"mode": "constant", "value": .04, "path": "r.csv"})     # a mis-set mode must not pass silently
    with pytest.raises(ValueError, match="Unknown constant dividend keys"):
        LiveConfig(tickers=("SPY",), dividend={"mode": "constant", "yields": {"SPY": .01}, "path": "d.csv"})
    with pytest.raises(ValueError, match="finite numbers"):
        LiveConfig(tickers=("SPY",), dividend_yields={"SPY": "x"})
    path = tmp_path/"c.json"
    path.write_text(json.dumps(dict(tickers=["SPY"], rate={"mode": "series", "path": "rates/r.csv"}, dividend_yields={"SPY": .01})))
    loaded, _ = LiveConfig.load(path)
    assert loaded.base_dir == str(tmp_path) and loaded.rate_spec["mode"] == "series"
    both = tmp_path/"both.json"
    both.write_text(json.dumps(dict(tickers=["SPY"], dividend_yields={"SPY": .01}, dividend={"mode": "constant", "yields": {"SPY": .02}})))
    with pytest.raises(ValueError, match="not both"):
        LiveConfig.load(both)
    with pytest.raises(ValueError, match="config file's directory"):
        CarryInputs(dict(mode="series", path="relative.csv"), dict(mode="constant", yields={"SPY": .01}))   # no base_dir: refuse cwd resolution


def test_constant_mode_metadata_is_the_v1_shape():
    """The config block stored in every v1 snapshot's metadata.json, verbatim; key order matters for byte-identical metadata."""
    golden = {"provider": "dolt_eod", "tickers": ["SPY", "QQQ", "AAPL"], "rate": 0.04, "dividend_yields": {"AAPL": 0.005, "QQQ": 0.006, "SPY": 0.014},
              "volatility": None, "baseline_estimator": "close_to_close", "training_tier": "daily_eod", "data_root": "../data/eod-live-full",
              "interval_seconds": 900, "expirations": 4, "history_window": 60, "request_timeout_seconds": 15, "cycle_timeout_seconds": 180,
              "max_backoff_seconds": 7200, "max_quote_age_seconds": 180, "max_spot_age_seconds": 120, "max_timestamp_skew_seconds": 120,
              "min_open_interest": 0, "max_relative_spread": 0.25, "min_days": 2.0, "max_days": 365.0, "min_training_sessions": 12,
              "min_training_rows": 300, "training_lookback_sessions": 60, "max_rows_per_symbol_session": 500, "min_free_disk_mb": 500,
              "min_split_rows": 50, "retrain_every_sessions": 2, "promotion_min_improvement": 0.02, "auto_train": True,
              "assumptions_note": "Illustrative constant rate/yield inputs. Replace for your research observation period."}
    config, _ = LiveConfig.load(ROOT/"config"/"eod-full.json")
    public = config.public_dict()
    public["tickers"] = list(public["tickers"])
    assert json.dumps(public) == json.dumps(golden)


def test_v2_configs_differ_from_eod_full_only_in_carry_and_root():
    base = json.loads((ROOT/"config"/"eod-full.json").read_text())
    base_root = (ROOT/"config"/base["data_root"]).resolve()
    expected = {"C0": ("constant", "constant"), "C1": ("series", "constant"), "C2": ("constant", "series"), "C3": ("series", "series")}
    for name, (rate_mode, dividend_mode) in expected.items():
        path = ROOT/"config"/"v2"/f"{name}.json"
        raw = json.loads(path.read_text())
        assert {k: v for k, v in raw.items() if k not in ("rate", "dividend", "data_root")} == \
            {k: v for k, v in base.items() if k not in ("rate", "dividend_yields", "data_root")}
        assert (path.parent/raw["data_root"]).resolve() == base_root
        config, root = LiveConfig.load(path)
        assert root == base_root and config.rate_spec["mode"] == rate_mode and config.dividend_spec["mode"] == dividend_mode
        if rate_mode == "constant":
            assert config.rate == base["rate"]
        if dividend_mode == "constant":
            assert config.dividend_yields == base["dividend_yields"]
        carry = CarryInputs.from_config(config)
        assert carry.rate_for("2021-03-01") > 0 or rate_mode == "constant"
        assert carry.yield_for("SPY", "2021-03-01") > 0


def synthetic_frame(sessions=2):
    import exchange_calendars as xc
    days = xc.get_calendar("XNYS").sessions_in_range("2026-03-02", "2026-03-31")[:sessions]
    frames = []
    for day in days:
        stamp = pd.Timestamp(str(day.date())+"T15:00:00Z")
        rows = []
        for days_out in (45, 120):
            expiration = (stamp+pd.Timedelta(days=days_out)).date().isoformat()
            T = time_to_expiry(expiration, stamp)
            for strike in np.linspace(92, 108, 5):
                iv = .22+.5*np.log(100/strike)**2
                for kind in ("call", "put"):
                    mid = BlackScholesEngine(100, strike, T, .04, iv, .01).price(kind)
                    rows.append(dict(symbol="TEST", contractSymbol=f"T{expiration}{strike}{kind}", option_type=kind,
                                     expiration=expiration, as_of=stamp.isoformat(), spot=100, strike=strike, bid=mid*.995,
                                     ask=mid*1.005, volume=500, openInterest=1000, r=.04, q=.01, baseline_sigma=.2,
                                     baseline_source="fixture", data_kind="market"))
        analyzed, _ = analyze_options(pd.DataFrame(rows), american_steps=None)
        analyzed["session_date"] = str(day.date())
        frames.append(analyzed)
    frame = pd.concat(frames, ignore_index=True)
    frame["observation_id"] = [f"obs-{i}" for i in range(len(frame))]
    return frame


def test_r_and_q_reach_pricing_features_and_the_iv_target():
    frame = synthetic_frame()
    carry = CarryInputs(dict(mode="constant", value=.01), dict(mode="constant", yields={"TEST": .03}))
    kept, failures = apply_carry(frame, carry)
    assert failures.empty and len(kept) == len(frame)
    assert (kept.r == .01).all() and (kept.q == .03).all() and (kept.effective_r == .01).all() and (kept.effective_q == .03).all()
    features, names = basis(kept, ["TEST"])
    assert np.allclose(features[:, names.index("rate_time")], .01*kept["T"]) and np.allclose(features[:, names.index("yield_time")], .03*kept["T"])
    before = evaluate(None, frame)[1]
    after = evaluate(None, kept)[1]
    exact = [BlackScholesEngine(row.spot, row.strike, row.T, .01, row.baseline_sigma, .03).price(row.option_type) for row in kept.itertuples()]
    assert np.allclose(after, exact) and not np.allclose(before, after)   # baseline pricing is BSM under the new r and q
    only_r, _ = apply_carry(frame, CarryInputs(dict(mode="constant", value=.01), dict(mode="constant", yields={"TEST": .01})), resolve_iv=False)
    only_q, _ = apply_carry(frame, CarryInputs(dict(mode="constant", value=.04), dict(mode="constant", yields={"TEST": .03})), resolve_iv=False)
    assert not np.allclose(evaluate(None, only_r)[1], before) and not np.allclose(evaluate(None, only_q)[1], before)
    assert not np.allclose(kept.iv_brent_volatility, frame.iv_brent_volatility)  # the target was re-solved under it
    repriced = [BlackScholesEngine(row.spot, row.strike, row.T, row.r, row.iv_brent_volatility, row.q).price(row.option_type)
                for row in kept.itertuples()]
    assert np.allclose(repriced, kept.mid, atol=1e-6)
    same = CarryInputs(dict(mode="constant", value=.04), dict(mode="constant", yields={"TEST": .01}))
    unchanged, _ = apply_carry(frame, same)
    assert np.allclose(unchanged.iv_brent_volatility, frame.iv_brent_volatility, atol=1e-9)   # v1 carry reproduces v1 targets


def test_apply_carry_records_unavailable_sessions(tmp_path):
    frame = synthetic_frame(sessions=2)
    first, second = sorted(frame.session_date.unique())
    rates = write_fred(tmp_path/"r.csv", [(first, "4.0")])              # the first session has no strictly-prior quote
    carry = CarryInputs(dict(mode="series", path=str(rates)), dict(mode="constant", yields={"TEST": .01}))
    table = effective_carry(frame, carry)
    assert list(table.carry_failure) == ["rate_unavailable", ""]
    kept, failures = apply_carry(frame, carry)
    assert set(kept.session_date) == {second} and set(failures.session_date) == {first}
    assert set(failures.reason) == {"rate_unavailable"} and len(failures) == (frame.session_date == first).sum()
    assert np.allclose(kept.effective_r, math.log1p(.04))


def test_apply_carry_drops_rows_whose_target_does_not_identify_under_the_new_carry():
    frame = synthetic_frame(sessions=1)
    deep = frame.iloc[:1].copy()                                   # a deep in-the-money put whose mid sits below the r = 0 lower bound
    deep["strike"], deep["option_type"], deep["T"], deep["observation_id"] = 150.0, "put", 1.0, "deep-put"
    deep["mid"] = BlackScholesEngine(100, 150, 1.0, .04, .2, .01).price("put")
    deep["bid"], deep["ask"] = deep["mid"]*.99, deep["mid"]*1.01
    calm = frame.iloc[1:2].copy()                                  # a quote priced under the new carry at 350% volatility, above the 300% cap
    calm["observation_id"], calm["strike"], calm["T"] = "calm-call", 100.0, .5
    calm["mid"] = BlackScholesEngine(100, 100, .5, 0.0, 3.5, .01).price("call")
    calm["bid"], calm["ask"] = calm["mid"]*.99, calm["mid"]*1.01
    carry = CarryInputs(dict(mode="constant", value=0.0), dict(mode="constant", yields={"TEST": .01}))
    kept, failures = apply_carry(pd.concat([frame, deep, calm], ignore_index=True), carry)
    reasons = dict(zip(failures.observation_id, failures.reason, strict=True))
    assert reasons["deep-put"] == "iv_not_identified" and reasons["calm-call"] == "iv_outside_training_range"
    assert not set(kept.observation_id) & {"deep-put", "calm-call"} and len(kept) == len(frame)
    assert np.allclose(kept.identified_iv, kept.iv_brent_volatility)


def test_effective_carry_leaves_both_values_empty_on_any_failure(tmp_path):
    rates = write_fred(tmp_path/"r.csv", [("2020-01-02", "1.5")])
    dividends = tmp_path/"d.csv"
    dividends.write_text("symbol,ex_date,amount\nAAPL,2020-06-01,0.5\n")
    bars = tmp_path/"b.csv"
    bars_frame("AAPL", "2020-01-01", "2020-12-31", 100.0).to_csv(bars, index=False)
    carry = CarryInputs(dict(mode="series", path=str(rates), stale_days=400),
                        dict(mode="series", path=str(dividends), bars=str(bars), history_start="2020-06-01"))
    table = effective_carry(pd.DataFrame(dict(session_date=["2020-08-03"], symbol=["AAPL"])), carry)
    assert table.carry_failure.iloc[0] == "dividend_history_unavailable"          # the window starts before history_start
    assert np.isnan(table.effective_r.iloc[0]) and np.isnan(table.effective_q.iloc[0])

