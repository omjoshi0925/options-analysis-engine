"""Walk-forward correctness: leakage guards, fold accounting, and test statistics."""
import numpy as np
import pandas as pd
import pytest
from options_engine import BlackScholesEngine
from options_engine.analysis import analyze_options
from options_engine.data import time_to_expiry
from options_engine.walkforward import (WalkForwardSpec, circular_block_bootstrap_ci,
                                        hln_diebold_mariano, walk_forward, walk_forward_report)


@pytest.fixture(scope="module")
def learnable_frame():
    """~24 sessions with a stable smile the ridge basis can represent; near-zero noise."""
    import exchange_calendars as xc
    sessions = xc.get_calendar("XNYS").sessions_in_range("2026-03-02", "2026-04-15")[:24]
    frames = []
    for day in sessions:
        stamp = pd.Timestamp(str(day.date())+"T15:00:00Z")
        rows = []
        for days_out in (30, 90):
            expiration = (stamp+pd.Timedelta(days=days_out)).date().isoformat()
            T = time_to_expiry(expiration, stamp)
            for strike in np.linspace(90, 110, 9):
                m = np.log(100/strike)
                iv = .2*np.exp(.15+.4*m+.6*m*m)
                for kind in ("call", "put"):
                    mid = BlackScholesEngine(100, strike, T, .04, iv, .01).price(kind)
                    rows.append(dict(symbol="TEST", contractSymbol=f"T{expiration}{strike}{kind}",
                                     option_type=kind, expiration=expiration, as_of=stamp.isoformat(),
                                     spot=100, strike=strike, bid=mid*.995, ask=mid*1.005, volume=500,
                                     openInterest=1000, r=.04, q=.01, baseline_sigma=.2,
                                     baseline_source="fixture_fixed", data_kind="market"))
        analyzed, _ = analyze_options(pd.DataFrame(rows))
        analyzed["session_date"] = str(day.date())
        frames.append(analyzed)
    return pd.concat(frames, ignore_index=True)


def test_walk_forward_folds_leakage_and_learnability(learnable_frame):
    spec = WalkForwardSpec(min_train_sessions=12, gap=1, validation_sessions=2)
    result = walk_forward(learnable_frame, spec)
    table = result["folds"]
    sessions = sorted(learnable_frame.session_date.unique())
    assert len(table) == len(sessions)-13
    for fold in table.itertuples():
        assert fold.train_end < fold.evaluated_session
        gap_sessions = sessions[sessions.index(fold.train_end)+1:sessions.index(fold.evaluated_session)]
        assert len(gap_sessions) == 1  # the embargo session is never trained on or evaluated
    assert (table.model_loss < table.baseline_loss).all()
    assert table.alpha.isin(WalkForwardSpec().alphas).all()
    dm = hln_diebold_mariano(result["baseline_losses"], result["model_losses"])
    assert dm["favors"] == "model" and dm["p_value"] < .05


def test_rolling_window_caps_training(learnable_frame):
    spec = WalkForwardSpec(min_train_sessions=8, gap=0, validation_sessions=2,
                           window="rolling", max_train_sessions=8)
    table = walk_forward(learnable_frame, spec)["folds"]
    assert (table.train_sessions == 8).all()
    with pytest.raises(ValueError, match="rolling"):
        WalkForwardSpec(window="rolling")
    with pytest.raises(ValueError, match="at least"):
        walk_forward(learnable_frame.loc[learnable_frame.session_date < "2026-03-10"], WalkForwardSpec())


def test_diebold_mariano_properties():
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 1, 40)
    centered = noise-noise.mean()
    null = hln_diebold_mariano(centered, np.zeros(40))
    assert abs(null["statistic"]) < 1e-10 and null["p_value"] > .99
    strong = hln_diebold_mariano(np.full(20, 2.0)+rng.normal(0, .01, 20), np.zeros(20))
    assert strong["favors"] == "model" and strong["p_value"] < 1e-6
    constant = hln_diebold_mariano(np.full(10, 1.0), np.zeros(10))
    assert constant["statistic"] == np.inf and constant["p_value"] == 0.0
    n, h = 10, 1
    assert hln_diebold_mariano(noise[:n], np.zeros(n), h)["hln_correction"] == pytest.approx(np.sqrt((n+1-2*h+h*(h-1)/n)/n))
    with pytest.raises(ValueError, match="at least 8"):
        hln_diebold_mariano([1, 2, 3], [0, 0, 0])


def test_block_bootstrap_ci_covers_and_is_deterministic():
    rng = np.random.default_rng(9)
    series = .5+rng.normal(0, .3, 60)
    first = circular_block_bootstrap_ci(series, seed=4)
    second = circular_block_bootstrap_ci(series, seed=4)
    assert first == second
    assert first["low"] < .5 < first["high"] and first["excludes_zero"]
    assert first["block_length"] == round(60**(1/3))
    with pytest.raises(ValueError, match="block_length"):
        circular_block_bootstrap_ci(series, block_length=0)
    with pytest.raises(ValueError, match="at least 8"):
        circular_block_bootstrap_ci([1.0, 2.0])


def test_report_writes_artifacts_and_refuses_overwrite(tmp_path, learnable_frame):
    result = walk_forward(learnable_frame, WalkForwardSpec(min_train_sessions=8, gap=1, validation_sessions=2))
    significance = walk_forward_report(result, tmp_path/"report", n_boot=300, seed=1)
    assert (tmp_path/"report"/"folds.csv").exists()
    assert (tmp_path/"report"/"significance.json").exists()
    text = (tmp_path/"report"/"REPORT.md").read_text()
    assert "not a forecast of option returns" in text
    assert significance["model_win_rate"] == 1.0
    assert significance["diebold_mariano"]["p_value"] < .05
    with pytest.raises(ValueError, match="exists"):
        walk_forward_report(result, tmp_path/"report")
