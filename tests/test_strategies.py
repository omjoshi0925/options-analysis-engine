import math
import numpy as np
import pytest
from options_engine import BlackScholesEngine, Leg, Strategy, PRESETS, preset

ARGS = dict(S=100.0, T=.5, r=.04, sigma=.25, q=.01)


def price(kind, K):
    return BlackScholesEngine(100.0, K, .5, .04, .25, .01).price(kind)


def test_long_call_structure():
    s = preset("long_call", **ARGS)
    premium = price("call", 100)
    assert s.net_premium == pytest.approx(premium)
    summary = s.summary()
    assert summary["breakevens"] == [pytest.approx(100+premium)]
    assert summary["max_loss"] == pytest.approx(-premium) and summary["unbounded_profit"] and not summary["unbounded_loss"]
    assert summary["max_profit"] == math.inf
    assert s.payoff(100+premium) == pytest.approx(0) and s.payoff(50) == pytest.approx(-premium)
    assert s.value(**ARGS) == pytest.approx(0)


def test_straddle_breakevens_and_spread_bounds():
    straddle = preset("long_straddle", **ARGS)
    total = price("call", 100)+price("put", 100)
    assert straddle.breakevens() == pytest.approx([100-total, 100+total])
    assert straddle.summary()["max_loss"] == pytest.approx(-total)
    spread = preset("bull_call_spread", width=10, **ARGS)
    debit = price("call", 100)-price("call", 110)
    summary = spread.summary()
    assert summary["max_profit"] == pytest.approx(10-debit) and summary["max_loss"] == pytest.approx(-debit)
    assert summary["breakevens"] == [pytest.approx(100+debit)]
    assert not summary["unbounded_profit"] and not summary["unbounded_loss"] and summary["right_slope"] == 0


def test_iron_condor_and_butterfly():
    condor = preset("iron_condor", width=5, **ARGS)
    credit = -condor.net_premium
    assert credit > 0
    summary = condor.summary()
    assert summary["max_profit"] == pytest.approx(credit) and summary["max_loss"] == pytest.approx(credit-5)
    assert len(summary["breakevens"]) == 2 and summary["strikes"] == [90, 95, 105, 110]
    butterfly = preset("long_call_butterfly", width=5, **ARGS)
    assert butterfly.payoff(100) == pytest.approx(5-butterfly.net_premium)
    assert butterfly.payoff(90) == pytest.approx(-butterfly.net_premium) and butterfly.payoff(120) == pytest.approx(-butterfly.net_premium)


def test_short_call_is_unbounded_and_stock_breakeven():
    short = preset("short_call", **ARGS)
    summary = short.summary()
    assert summary["unbounded_loss"] and summary["max_loss"] == -math.inf and summary["max_profit"] == pytest.approx(price("call", 100))
    stock = Strategy("stock", (Leg("stock", 1, premium=95.0),))
    assert stock.breakevens() == [95.0] and stock.summary()["unbounded_profit"]
    assert stock.payoff(np.array([90.0, 95.0, 100.0])).tolist() == pytest.approx([-5, 0, 5])


def test_parity_greeks_and_priced_marks():
    synthetic_forward = Strategy.priced("forward", [Leg("call", 1, 100), Leg("put", -1, 100)], **ARGS)
    m = BlackScholesEngine(**{**ARGS, "K": 100})
    assert synthetic_forward.net_premium == pytest.approx(m.adjusted_spot-m.discounted_strike)
    greeks = synthetic_forward.greeks(**ARGS)
    assert greeks["Delta"] == pytest.approx(math.exp(-.01*.5)) and greeks["Gamma"] == pytest.approx(0, abs=1e-12)
    covered = preset("covered_call", **ARGS)
    call_delta = BlackScholesEngine(100, 105, .5, .04, .25, .01).analytical_greeks("call", "market")["Delta"]
    assert covered.greeks(**ARGS, units="market")["Delta"] == pytest.approx(1-call_delta)
    summary = covered.summary(**ARGS)
    assert summary["current_value"] == pytest.approx(0) and set(summary["greeks"]) == {"Delta", "Gamma", "Theta", "Vega", "Rho"}
    later = covered.value(110, .25, .04, .25, .01)
    assert later > 0


def test_every_preset_builds_and_payoff_matches_leg_sum():
    grid = np.linspace(50, 150, 11)
    for name in PRESETS:
        s = preset(name, **ARGS)
        expected = sum(leg.quantity*(leg.intrinsic(grid)-leg.premium) for leg in s.legs)
        np.testing.assert_allclose(s.payoff(grid), expected)
        assert all(root > 0 for root in s.breakevens())


@pytest.mark.parametrize("bad", [dict(kind="future", quantity=1), dict(kind="call", quantity=0, strike=100), dict(kind="put", quantity=1),
                                 dict(kind="stock", quantity=1, strike=100), dict(kind="call", quantity=1, strike=100, premium=-1)])
def test_invalid_legs(bad):
    with pytest.raises(ValueError):
        Leg(**bad)


def test_invalid_strategies_and_presets():
    with pytest.raises(ValueError, match="at least one leg"):
        Strategy("empty", ())
    with pytest.raises(ValueError, match="premium"):
        Strategy("unpriced", (Leg("call", 1, 100),))
    with pytest.raises(ValueError, match="Unknown preset"):
        preset("iron_butterfly_condor", **ARGS)
    with pytest.raises(ValueError, match="width"):
        preset("iron_condor", width=60, **ARGS)
    with pytest.raises(ValueError, match="width"):
        preset("long_call", width=-1, **ARGS)


def test_strategy_figure_renders():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from options_engine.plots import strategy_figure
    fig = strategy_figure(preset("iron_condor", **ARGS), **ARGS)
    assert len(fig.axes) == 1 and len(fig.axes[0].lines) >= 4
    plt.close(fig)
