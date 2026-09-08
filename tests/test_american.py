import numpy as np
import pytest
from options_engine import (BlackScholesEngine, binomial_price, binomial_analysis, binomial_greeks,
                            early_exercise_boundary)


def test_hull_five_step_american_put_reference():
    # Hull, Options, Futures, and Other Derivatives: S=50, K=50, r=10%, sigma=40%, T=5 months, 5 steps.
    assert binomial_price(50, 50, 5/12, .10, .40, 0.0, "put", steps=5) == pytest.approx(4.49, abs=5e-3)


@pytest.mark.parametrize("kind", ["call", "put"])
def test_european_tree_converges_to_closed_form(kind):
    m = BlackScholesEngine(100, 95, .75, .03, .3, .02)
    errors = [abs(binomial_price(100, 95, .75, .03, .3, .02, kind, n, american=False)-m.price(kind)) for n in (50, 200, 800)]
    assert errors[0] > errors[1] > errors[2]
    assert errors[2] < 5e-3


def test_tree_parity_and_no_call_premium_without_dividends():
    m = BlackScholesEngine(100, 105, 1.0, .05, .25, 0.0)
    call = binomial_price(100, 105, 1.0, .05, .25, 0.0, "call", 300, american=False)
    put = binomial_price(100, 105, 1.0, .05, .25, 0.0, "put", 300, american=False)
    assert call-put == pytest.approx(m.adjusted_spot-m.discounted_strike, abs=1e-10)
    result = binomial_analysis(100, 105, 1.0, .05, .25, 0.0, "call", 300)
    assert result.early_exercise_premium == pytest.approx(0.0, abs=1e-12)
    assert result.price == pytest.approx(result.european_tree_price, abs=1e-12)
    assert result.bsm_price == m.price("call")


def test_put_premium_positive_and_deep_itm_equals_intrinsic():
    result = binomial_analysis(100, 100, 1.0, .05, .2, 0.0, "put", 400)
    assert result.early_exercise_premium > 0.01
    assert result.price > result.bsm_price
    assert abs(result.discretization_error) < 5e-3
    assert binomial_price(50, 100, 1.0, .05, .2, 0.0, "put", 200) == pytest.approx(50.0, abs=1e-9)
    # A dividend-paying stock makes early exercise of a deep in-the-money call optimal.
    assert binomial_analysis(200, 100, 1.0, .01, .2, .08, "call", 200).early_exercise_premium > 0.5


def test_exercise_boundary_shape():
    boundary = early_exercise_boundary(100, 100, 1.0, .05, .2, 0.0, "put", 200)
    critical = boundary.critical_spot.dropna()
    assert len(boundary) == 200 and len(critical) > 100
    assert (critical < 100).all()
    assert critical.iloc[-1] > critical.iloc[0]
    assert 0.9*100 <= critical.iloc[-1] <= 100
    assert np.isnan(boundary.critical_spot.iloc[0])


def test_tree_greeks_match_closed_form_for_european():
    m = BlackScholesEngine(100, 100, .5, .04, .3, .01)
    analytic = m.analytical_greeks("put")
    tree = binomial_greeks(100, 100, .5, .04, .3, .01, "put", 1000, american=False)
    # Observed 1000-step agreement is within 0.1%; tolerances leave a margin for platform rounding.
    assert tree["Delta"] == pytest.approx(analytic["Delta"], abs=1e-3)
    assert tree["Gamma"] == pytest.approx(analytic["Gamma"], rel=1e-2)
    assert tree["Theta"] == pytest.approx(analytic["Theta"], rel=1e-2)
    assert tree["Vega"] == pytest.approx(analytic["Vega"], rel=1e-2)
    assert tree["Rho"] == pytest.approx(analytic["Rho"], rel=1e-2)
    market = binomial_greeks(100, 100, .5, .04, .3, .01, "put", 1000, american=False, units="market")
    assert market["Theta"] == tree["Theta"]/365 and market["Vega"] == tree["Vega"]/100
    american = binomial_greeks(100, 100, .5, .04, .3, .01, "put", 1000, american=True)
    assert american["Delta"] < tree["Delta"] < 0


@pytest.mark.parametrize("kwargs", [dict(T=0), dict(sigma=0), dict(steps=0), dict(steps=2.5), dict(r=5, sigma=.01, steps=1)])
def test_invalid_tree_inputs(kwargs):
    args = dict(S=100, K=100, T=1, r=.05, sigma=.2, q=0, option_type="call", steps=10)
    args.update(kwargs)
    with pytest.raises(ValueError):
        binomial_price(**args)
    with pytest.raises(ValueError):
        binomial_greeks(100, 100, 1, .05, .2, units="bogus")
