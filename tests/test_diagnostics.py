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
    assert "## Early-exercise premium (American baseline)" in text and "- puts: n=" in text


def test_early_exercise_columns_are_consistent(analyzed):
    frame, _, _ = analyzed
    for column in ("american_baseline_price", "early_exercise_premium", "tree_discretization_error", "american_error", "american_within_spread"):
        assert frame[column].notna().all(), column
    assert (frame.early_exercise_premium >= 0).all()
    # American tree = European closed form + discretization error + early-exercise premium, by construction.
    np.testing.assert_allclose(frame.american_baseline_price, frame.baseline_price+frame.tree_discretization_error+frame.early_exercise_premium, atol=1e-12)
    np.testing.assert_allclose(frame.american_error, frame.mid-frame.american_baseline_price, atol=1e-12)
    puts = frame.loc[frame.option_type == "put"]
    assert puts.early_exercise_premium.max() > 0.01
    assert (frame.tree_discretization_error.abs() < 0.05).all()
    assert (frame.loc[frame.option_type == "call"].early_exercise_premium < puts.early_exercise_premium.max()).all()


def test_tree_can_be_skipped_and_step_count_is_validated():
    raw, _ = synthetic_snapshot()
    frame, _ = analyze_options(raw.head(12), american_steps=None)
    assert frame.american_baseline_price.isna().all() and frame.early_exercise_premium.isna().all()
    for steps in (0, -5, 2.5, True):
        with pytest.raises(ValueError, match="american_steps"):
            analyze_options(raw.head(12), american_steps=steps)


def test_metrics_report_american_baseline_when_available(analyzed):
    from options_engine.analysis import metrics
    frame, audit, meta = analyzed
    result = metrics(frame)
    assert set(("american_mae", "american_rmse", "american_within_bid_ask_pct", "mean_early_exercise_premium")) <= set(result)
    assert result["american_mae"] > 0 and result["mean_early_exercise_premium"] >= 0
    skipped, _ = analyze_options(synthetic_snapshot()[0].head(12), american_steps=None)
    assert "american_mae" not in metrics(skipped)
