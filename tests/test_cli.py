import json
import sys
import pytest
from options_engine import BlackScholesEngine
from options_engine.cli import parser, run, main


def invoke(capsys, *argv):
    code = run(parser().parse_args(list(argv)))
    return code, json.loads(capsys.readouterr().out)


def test_price_command_matches_engine(capsys):
    code, out = invoke(capsys, "price", "--S", "100", "--K", "95", "--days", "45", "--r", "0.04", "--sigma", "0.3", "--q", "0.01",
                       "--type", "put", "--paths", "20000")
    m = BlackScholesEngine(100, 95, 45/365, .04, .3, .01)
    assert code == 0
    assert out["call"] == pytest.approx(m.price("call")) and out["put"] == pytest.approx(m.price("put"))
    assert out["inputs"]["T"] == pytest.approx(45/365)
    assert out["greeks"]["put"]["market"]["Theta"] == pytest.approx(m.analytical_greeks("put", "market")["Theta"])
    assert out["greeks"]["call"]["raw"]["Delta"] == pytest.approx(m.analytical_greeks("call")["Delta"])
    assert out["american"]["option_type"] == "put" and out["american"]["early_exercise_premium"] >= 0
    assert out["american"]["price"] >= out["put"]-0.05
    assert abs(out["monte_carlo"]["z_score"]) < 4 and out["monte_carlo"]["paths"] == 20000


def test_price_at_expiry_has_no_greeks_or_simulation(capsys):
    code, out = invoke(capsys, "price", "--S", "110", "--K", "100", "--T", "0", "--r", "0.04", "--sigma", "0.3")
    assert code == 0 and out["call"] == 10 and out["put"] == 0
    assert "greeks" not in out and "american" not in out and "monte_carlo" not in out and out["d1"] is None


def test_iv_round_trip_and_failure_exit_code(capsys):
    price = BlackScholesEngine(100, 100, .5, .02, .35).price("call")
    code, out = invoke(capsys, "iv", "--price", str(price), "--S", "100", "--K", "100", "--T", "0.5", "--r", "0.02")
    assert code == 0 and out["converged"] and out["volatility"] == pytest.approx(.35, abs=1e-8) and out["method"] == "brent"
    code, out = invoke(capsys, "iv", "--price", "150", "--S", "100", "--K", "100", "--T", "0.5", "--r", "0.02", "--method", "newton")
    assert code == 2 and out["status"] == "outside_european_bounds" and out["volatility"] is None


def test_strategy_command_summary_and_plot(capsys, tmp_path):
    plot = tmp_path/"figures"/"condor.png"
    code, out = invoke(capsys, "strategy", "--preset", "iron_condor", "--S", "100", "--days", "30", "--r", "0.04", "--sigma", "0.2",
                       "--width", "5", "--plot", str(plot))
    assert code == 0 and out["strikes"] == [90, 95, 105, 110] and len(out["breakevens"]) == 2
    assert out["max_profit"] == pytest.approx(-out["net_premium"]) and plot.exists()
    assert out["current_value"] == pytest.approx(0, abs=1e-12) and set(out["greeks"]) == {"Delta", "Gamma", "Theta", "Vega", "Rho"}
    code, out = invoke(capsys, "strategy", "--preset", "long_call", "--S", "100", "--T", "0.25", "--r", "0.04", "--sigma", "0.2")
    assert code == 0 and out["max_profit"] is None and out["unbounded_profit"] and out["breakevens"][0] > 100
    code, out = invoke(capsys, "strategy", "--preset", "long_put", "--S", "100", "--T", "0", "--r", "0.04", "--sigma", "0.2", "--strike", "105")
    assert code == 0 and "greeks" not in out and out["net_premium"] == pytest.approx(5)


def test_missing_horizon_is_reported_as_an_error(monkeypatch, capsys):
    with pytest.raises(ValueError, match="--T or --days"):
        run(parser().parse_args(["price", "--S", "100", "--K", "100", "--r", "0.04", "--sigma", "0.2"]))
    monkeypatch.setattr(sys, "argv", ["options-engine", "iv", "--price", "5", "--S", "100", "--K", "100", "--r", "0.04"])
    assert main() == 2
    assert "Provide --T or --days" in capsys.readouterr().err
