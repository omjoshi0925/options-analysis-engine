"""Diagnostics on the synthetic chain; software behaviour only, never market evidence."""
import numpy as np
import pytest
from options_engine.analysis import analyze_options, implied_forward_diagnostics, write_report
from options_engine.demo import synthetic_snapshot


@pytest.fixture(scope="module")
def analyzed():
    raw, meta = synthetic_snapshot()
    frame, audit = analyze_options(raw)
    return frame, audit, meta


def test_parity_fit_recovers_generating_rate_and_yield(analyzed):
    frame, _, _ = analyzed
    result = implied_forward_diagnostics(frame)
    fitted = result.loc[result.status == "ok"]
    assert len(fitted) == 6 and set(fitted.symbol) == {"DEMO_A", "DEMO_B"}
    np.testing.assert_allclose(fitted.implied_rate, .04, atol=1e-6)
    np.testing.assert_allclose(fitted.implied_yield, .01, atol=1e-6)
    np.testing.assert_allclose(fitted.rate_difference, 0, atol=1e-6)
    np.testing.assert_allclose(fitted.implied_forward, fitted.spot*np.exp((.04-.01)*fitted["T"]), rtol=1e-6)
    assert (fitted.fit_rmse < 1e-8).all() and (fitted.r_squared > 1-1e-9).all()
    assert (fitted.n_pairs >= 3).all()


def test_inflated_puts_lower_the_implied_forward(analyzed):
    frame, _, _ = analyzed
    clean = implied_forward_diagnostics(frame).set_index(["symbol", "expiration"])
    inflated = frame.copy()
    inflated.loc[inflated.option_type == "put", "mid"] *= 1.05
    biased = implied_forward_diagnostics(inflated).set_index(["symbol", "expiration"])
    assert (biased.implied_forward < clean.implied_forward).all()
    assert (biased.fit_rmse > clean.fit_rmse).all()


def test_insufficient_pairs_are_reported_not_fitted(analyzed):
    frame, _, _ = analyzed
    single = frame.loc[(frame.symbol == "DEMO_A") & (frame.expiration == "2026-10-16") & (frame.strike == 100)]
    result = implied_forward_diagnostics(single)
    assert len(result) == 1 and result.iloc[0].status == "insufficient_pairs"
    assert np.isnan(result.iloc[0].implied_rate)
    assert implied_forward_diagnostics(frame.loc[frame.option_type == "call"]).empty


def test_report_includes_parity_fit(analyzed, tmp_path):
    frame, audit, meta = analyzed
    write_report(frame, audit, meta, tmp_path)
    text = (tmp_path/"REPORT.md").read_text()
    assert "## Implied forward, rate, and yield from put-call parity" in text
    assert "implied r 0.0400 (assumed 0.0400)" in text
    assert (tmp_path/"implied_forward.csv").exists()
