"""Design B baselines: B1 lookups and interpolation, the Amendment 4 carry convention, SVI fitting and its guards, set B accounting."""
import json
import math

import numpy as np
import pandas as pd
import pytest

from options_engine import BlackScholesEngine
from options_engine.baselines import (b1_baseline, b2_baseline, build_design_b, butterfly_free, fit_slice, fit_svi,
                                      parameter_bounds_hold, svi_total_variance)
from options_engine.carry_inputs import CarryInputs, apply_carry
from options_engine.cli import parser, run
from options_engine.eod_import import import_eod
from options_engine.iv import implied_volatility
from test_eod_import import eod_config


def row(session, symbol, expiration, strike, kind, iv, spot=100.0, r=.04, q=.01, expiry_days=None):
    T = (pd.Timestamp(expiration)-pd.Timestamp(session)).days/365 if expiry_days is None else expiry_days/365
    engine = BlackScholesEngine(spot, strike, T, r, iv, q)
    mid = engine.price(kind)
    return dict(observation_id=f"{session}-{symbol}-{expiration}-{float(strike)}-{kind}", session_date=session, symbol=symbol,
                contractSymbol=f"{symbol}{expiration}{kind[0].upper()}{strike}", expiration=expiration, strike=float(strike), option_type=kind,
                spot=spot, T=T, r=r, q=q, mid=mid, bid=mid*.99, ask=mid*1.01, baseline_sigma=.2, iv_brent_volatility=iv,
                iv_brent_vega=spot*math.exp(-q*T)*math.sqrt(T)*math.exp(-engine.d1**2/2)/math.sqrt(2*math.pi), days_to_expiry=T*365)


def test_b1_same_contract_interpolation_and_drop_reasons():
    rows = []
    # session d1 holds a call smile at strikes 90, 100, 110 for expiry E and a lone put; d0 is the first session.
    for strike, iv in ((90, .30), (100, .25), (110, .20)):
        rows.append(row("2024-01-04", "X", "2024-03-15", strike, "call", iv))
    rows.append(row("2024-01-04", "X", "2024-03-15", 100, "put", .27))
    rows.append(row("2024-01-02", "X", "2024-03-15", 100, "call", .26))
    # session d2 (t): same contract, an interpolated strike, an out-of-range strike, a put needing a one-point slice, a new expiry.
    rows += [row("2024-01-08", "X", "2024-03-15", 100, "call", .24), row("2024-01-08", "X", "2024-03-15", 105, "call", .23),
             row("2024-01-08", "X", "2024-03-15", 120, "call", .19), row("2024-01-08", "X", "2024-03-15", 95, "put", .28),
             row("2024-01-08", "X", "2024-04-19", 100, "call", .22), row("2024-01-08", "X", "2024-03-15", 100, "put", .26),
             row("2024-01-08", "Y", "2024-03-15", 100, "call", .22)]
    frame = pd.DataFrame(rows)
    b1 = b1_baseline(frame).set_index("observation_id")
    same = b1.loc["2024-01-08-X-2024-03-15-100.0-call"]
    assert same.b1_source == "same_contract" and same.b1_sigma == pytest.approx(.25) and same.prior_session == "2024-01-04" and same.gap_days == 4
    inter = b1.loc["2024-01-08-X-2024-03-15-105.0-call"]
    assert inter.b1_source == "interpolated" and inter.b1_sigma == pytest.approx(.225)
    assert b1.loc["2024-01-08-X-2024-03-15-120.0-call"].b1_reason == "strike_outside_prior_range"     # never extrapolate
    assert b1.loc["2024-01-08-X-2024-03-15-95.0-put"].b1_reason == "single_strike_at_prior_session"
    assert b1.loc["2024-01-08-X-2024-03-15-100.0-put"].b1_source == "same_contract"
    assert b1.loc["2024-01-08-X-2024-04-19-100.0-call"].b1_reason == "expiry_absent_at_prior_session"
    assert b1.loc["2024-01-08-Y-2024-03-15-100.0-call"].b1_reason == "no_prior_session"
    assert b1.loc["2024-01-02-X-2024-03-15-100.0-call"].b1_reason == "no_prior_session"
    assert b1.loc["2024-01-04-X-2024-03-15-100.0-call"].b1_source == "same_contract" and b1.loc["2024-01-04-X-2024-03-15-100.0-call"].gap_days == 2
    assert b1.loc["2024-01-04-X-2024-03-15-100.0-put"].b1_reason == "type_absent_at_prior_session"   # d0 has calls only
    with pytest.raises(ValueError, match="twice"):
        b1_baseline(pd.concat([frame, frame.iloc[:1]], ignore_index=True))


def test_b1_uses_the_prior_session_carry_convention(tmp_path):
    """Amendment 4: the t-1 mid is inverted under r_{t-1}; inverting it under r_t would give a different sigma."""
    (tmp_path/"rates.csv").write_text("observation_date,DGS3MO\n2024-01-03,1.0\n2024-01-05,5.0\n")   # r_{t-1} ~ 1%, r_t ~ 5%
    carry = CarryInputs(dict(mode="series", path=str(tmp_path/"rates.csv"), stale_days=400), dict(mode="constant", yields={"X": .01}))
    prior_rate, later_rate = carry.rate_for("2024-01-04"), carry.rate_for("2024-01-08")
    assert prior_rate == pytest.approx(math.log1p(.01)) and later_rate == pytest.approx(math.log1p(.05))
    rows = [row("2024-01-04", "X", "2024-06-21", 100, "call", .25, r=prior_rate), row("2024-01-08", "X", "2024-06-21", 100, "call", .3, r=later_rate)]
    frame, failures = apply_carry(pd.DataFrame(rows), carry)
    assert failures.empty
    b1 = b1_baseline(frame).set_index("observation_id")
    sigma = b1.loc["2024-01-08-X-2024-06-21-100.0-call"].b1_sigma
    prior = frame.set_index("observation_id").loc["2024-01-04-X-2024-06-21-100.0-call"]
    assert sigma == pytest.approx(.25, abs=1e-6)                                  # inverted under t-1 conditions
    wrong = implied_volatility(prior.mid, prior.spot, prior.strike, prior["T"], later_rate, prior.q, "call").volatility
    assert abs(wrong-.25) > 1e-3 and sigma != pytest.approx(wrong, abs=1e-4)      # t's carry on a t-1 price is a different number


def synthetic_slice(session, expiration, params, strikes, spot=100.0, r=.02, q=.01, kind_split=True):
    T = (pd.Timestamp(expiration)-pd.Timestamp(session)).days/365
    forward = spot*math.exp((r-q)*T)
    rows = []
    for strike in strikes:
        k = math.log(strike/forward)
        iv = math.sqrt(svi_total_variance(k, params)/T)
        kind = ("put" if strike < forward else "call") if kind_split else "call"
        rows.append(row(session, "X", expiration, strike, kind, iv, spot=spot, r=r, q=q))
    return pd.DataFrame(rows)


def test_svi_recovers_a_known_slice():
    params = (.02, .4, -.4, .05, .2)
    strikes = np.round(np.linspace(80, 125, 15), 1)
    slice_frame = synthetic_slice("2024-01-04", "2024-07-19", params, strikes)
    result = fit_slice(slice_frame)
    assert result["ok"], result
    forward = result["forward"]
    probe = np.linspace(math.log(82/forward), math.log(123/forward), 25)
    assert np.allclose(svi_total_variance(probe, result["params"]), svi_total_variance(probe, params), atol=2e-5)
    assert parameter_bounds_hold(result["params"]) and butterfly_free(result["params"], result["k_low"], result["k_high"])
    fitted, info = fit_svi(*(lambda p: (p["k"], p["w"], p["weights"]))(__import__("options_engine.baselines", fromlist=["slice_points"]).slice_points(slice_frame)))
    assert fitted is not None and info["cost"] < 1e-8


def test_butterfly_rejection_triggers_fallback():
    vogt = (-.0410, .1331, .3060, .3586, .4153)                                    # Gatheral-Jacquier's arbitrageable example: g < 0 near k = 0.88
    assert parameter_bounds_hold(vogt) and not butterfly_free(vogt, -1.0, 1.0)
    arb = (.00128, .7468, -.8244, .3413, .0427)                                    # bounds hold, g < 0 near the money (k = -0.05)
    assert parameter_bounds_hold(arb) and not butterfly_free(arb, -.4, .4)
    strikes = np.round(np.linspace(70, 140, 16), 1)
    prior = synthetic_slice("2024-01-04", "2025-01-03", arb, strikes)
    fitted = fit_slice(prior)
    assert not fitted["ok"] and fitted["reason"] == "butterfly", fitted            # the fit recovers the slice, the check rejects it
    current = synthetic_slice("2024-01-05", "2025-01-03", arb, strikes[2:-2])
    frame = pd.concat([prior, current], ignore_index=True)
    b1 = b1_baseline(frame)
    b2, accounting = b2_baseline(frame, b1)
    at_t = b2.loc[b2.observation_id.isin(current.observation_id)]
    assert (at_t.b2_source == "fallback_b1").all() and (at_t.b2_reason == "butterfly").all()
    assert accounting["slices_fallback_by_reason"] == {"butterfly": 1} and accounting["slice_fallback_rate"] == 1.0 and accounting["fallback_contaminated"]
    merged = at_t.merge(b1[["observation_id", "b1_sigma"]], on="observation_id")
    assert np.allclose(merged.b2_sigma, merged.b1_sigma)
    good = (.02, .4, -.4, .05, .2)
    healthy = pd.concat([synthetic_slice("2024-01-04", "2025-01-03", good, strikes), synthetic_slice("2024-01-05", "2025-01-03", good, strikes[2:-2])],
                        ignore_index=True)
    b2_good, accounting_good = b2_baseline(healthy, b1_baseline(healthy))
    assert accounting_good["slice_fallback_rate"] == 0 and (b2_good.b2_source == "svi").all()
    current_good = healthy.loc[healthy.session_date == "2024-01-05"].set_index("observation_id")
    check = b2_good.set_index("observation_id").loc[current_good.index]
    assert np.allclose(check.b2_sigma, current_good.iv_brent_volatility, rtol=2e-3)   # the persisted smile reproduces a stationary smile


def test_set_b_accounting_sums():
    good = (.02, .4, -.4, .05, .2)
    strikes = np.round(np.linspace(80, 125, 10), 1)
    frame = pd.concat([synthetic_slice("2024-01-04", "2024-07-19", good, strikes), synthetic_slice("2024-01-05", "2024-07-19", good, strikes),
                       synthetic_slice("2024-01-05", "2024-08-16", good, strikes[:6])], ignore_index=True)
    keys, table, summary = build_design_b(frame)
    assert summary["kept"]+summary["dropped"] == summary["candidates"] == len(frame)
    assert sum(summary["dropped_by_reason"].values()) == summary["dropped"] == len(strikes)+6       # the first session and the new expiry
    assert summary["dropped_by_reason"] == {"expiry_absent_at_prior_session": 6, "no_prior_session": len(strikes)}
    assert sum(summary["b1_by_source"].values()) == summary["kept"] == len(keys) == len(table)
    assert sum(summary["b2"]["rows_by_source"].values()) == summary["kept"]
    assert set(table.columns) >= {"b1_sigma", "b1_source", "gap_days", "b2_sigma", "b2_source", "b2_reason", "rv_sigma"}
    assert summary["b1_vs_rv"]["median_abs_difference"] > 0 and summary["gap_days"]["median"] == 1


def persistent_fixture(base, sessions=20, sigma=.2):
    """Twenty sessions whose two expiries and strike grid persist, so contracts exist at the prior session."""
    import exchange_calendars as xc
    days = [str(d.date()) for d in xc.get_calendar("XNYS").sessions_in_range("2023-01-01", "2023-12-31")]
    chain_days = days[70:70+sessions]
    expiries = (days[70+sessions+8], days[70+sessions+50])
    rng = np.random.default_rng(5)
    closes = 100*np.exp(np.cumsum(rng.normal(0, sigma/np.sqrt(252), len(days))))
    underlying = pd.DataFrame(dict(date=days[:70+sessions], act_symbol="TEST", open=closes[:70+sessions]*.999, high=closes[:70+sessions]*1.01,
                                   low=closes[:70+sessions]*.99, close=closes[:70+sessions]))
    rows = []
    for i, day in enumerate(chain_days):
        spot = closes[70+i]
        for expiration in expiries:
            T = (pd.Timestamp(expiration)-pd.Timestamp(day)).days/365
            for strike in np.arange(88.0, 113.0, 2.5):
                iv = sigma*np.exp(.1+.3*np.log(spot/strike)+.5*np.log(spot/strike)**2)
                for kind in ("Call", "Put"):
                    mid = BlackScholesEngine(spot, strike, T, .04, iv, .01).price(kind.lower())
                    rows.append(dict(date=day, act_symbol="TEST", expiration=expiration, strike=strike, call_put=kind,
                                     bid=round(mid*.99, 4), ask=round(mid*1.01, 4), vol=round(iv, 4)))
    pd.DataFrame(rows).to_csv(base/"chain.csv", index=False)
    underlying.to_csv(base/"underlying.csv", index=False)
    return chain_days


def invoke(capsys, *argv):
    code = run(parser().parse_args([str(a) for a in argv]))
    return code, json.loads(capsys.readouterr().out)


def test_baselines_build_and_walk_forward_override(tmp_path, capsys):
    chain_days = persistent_fixture(tmp_path)
    root = tmp_path/"data"/"root"
    import_eod(tmp_path/"chain.csv", tmp_path/"underlying.csv", eod_config(), root)
    (tmp_path/"rates.csv").write_text("observation_date,DGS3MO\n"+"".join(f"{d},{2.0+.1*math.sin(i):.4f}\n" for i, d in enumerate(chain_days)))
    settings = dict(eod_config().public_dict(), data_root="data/root", rate={"mode": "series", "path": "rates.csv"},
                    dividend={"mode": "constant", "yields": {"TEST": .01}})
    settings.pop("dividend_yields", None)
    (tmp_path/"K3.json").write_text(json.dumps(settings, indent=2, sort_keys=True))
    code, set_a = invoke(capsys, "observation-set", "build", "--configs", tmp_path/"K3.json", "--out", tmp_path/"set-A.csv")
    assert code == 0 and set_a["kept"] > 0
    code, built = invoke(capsys, "baselines", "build", "--config", tmp_path/"K3.json", "--observation-set", tmp_path/"set-A.csv",
                         "--out", tmp_path/"set-B.csv", "--baselines", tmp_path/"baselines-B.csv")
    assert code == 0 and built["kept"] > 0 and built["kept"]+sum(built["dropped_by_reason"].values()) == set_a["kept"]
    assert built["b1_by_source"].get("same_contract", 0) > 0 and built["b2"]["slices_attempted"] > 0
    sidecar = json.loads((tmp_path/"set-B.drops.json").read_text())
    assert sidecar["configs"]["K3"]["sha256"] and sidecar["baselines"]["rows"] == built["kept"] and sidecar["source_set"]["rows"] == set_a["kept"]
    table = pd.read_csv(tmp_path/"baselines-B.csv")
    assert set(table.columns) >= {"observation_id", "b1_sigma", "b1_source", "gap_days", "b2_sigma", "b2_source"}
    common = ["--min-train-sessions", "6", "--gap", "1", "--bootstrap", "200", "--observation-set", tmp_path/"set-B.csv"]
    code, m_rv = invoke(capsys, "walk-forward", "--config", tmp_path/"K3.json", "--output", tmp_path/"M-RV", *common)
    code, m_b1 = invoke(capsys, "walk-forward", "--config", tmp_path/"K3.json", "--output", tmp_path/"M-B1", *common,
                        "--baseline-file", tmp_path/"baselines-B.csv", "--baseline-column", "b1_sigma")
    code, b1_only = invoke(capsys, "walk-forward", "--config", tmp_path/"K3.json", "--output", tmp_path/"B1", *common,
                           "--baseline-file", tmp_path/"baselines-B.csv", "--baseline-column", "b1_sigma", "--baseline-only")
    assert code == 0 and m_b1["baseline"]["column"] == "b1_sigma" and m_b1["baseline"]["rows_without_value"] == 0 and b1_only["baseline_only"]
    assert "same_contract" in m_b1["baseline"]["by_source"]
    rv, mb1, alone = (pd.read_csv(tmp_path/name/"folds.csv") for name in ("M-RV", "M-B1", "B1"))
    assert list(rv.evaluated_session) == list(mb1.evaluated_session) == list(alone.evaluated_session)   # identical folds
    assert np.allclose(alone.baseline_mse, mb1.baseline_mse) and np.allclose(alone.model_mse, alone.baseline_mse)   # B1 alone == M(B1)'s baseline
    assert (alone.learned_coverage == 0).all() and not np.allclose(rv.baseline_mse, mb1.baseline_mse)               # a different base volatility
    assert (rv.evaluation_rows == mb1.evaluation_rows).all()
    with pytest.raises(ValueError, match="no column"):
        invoke(capsys, "walk-forward", "--config", tmp_path/"K3.json", "--output", tmp_path/"bad", *common,
               "--baseline-file", tmp_path/"baselines-B.csv", "--baseline-column", "nope")
