import pytest
from options_engine import BlackScholesEngine, monte_carlo_price


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("S,K,T,r,sigma,q", [(100, 100, 1, .05, .2, 0), (80, 100, .5, .02, .4, .03), (120, 100, 2, -.01, .3, .01)])
def test_monte_carlo_agrees_with_closed_form_within_standard_error(kind, S, K, T, r, sigma, q):
    result = monte_carlo_price(S, K, T, r, sigma, q, kind)
    assert result.bsm_price == BlackScholesEngine(S, K, T, r, sigma, q).price(kind)
    assert abs(result.z_score) < 4
    assert 0 < result.standard_error < result.bsm_price
    assert result.paths == 200_000 and result.antithetic


def test_error_scaling_antithetic_reduction_and_determinism():
    small = monte_carlo_price(100, 100, 1, .05, .2, 0, "call", paths=20_000)
    large = monte_carlo_price(100, 100, 1, .05, .2, 0, "call", paths=80_000)
    assert 0.4 < large.standard_error/small.standard_error < 0.6
    plain = monte_carlo_price(100, 100, 1, .05, .2, 0, "call", paths=80_000, antithetic=False)
    assert large.standard_error < plain.standard_error
    assert abs(plain.z_score) < 4
    assert monte_carlo_price(100, 100, 1, .05, .2, 0, "call", paths=20_000).price == small.price
    assert monte_carlo_price(100, 100, 1, .05, .2, 0, "call", paths=20_000, seed=1).price != small.price


def test_degenerate_cases_are_exact():
    expired = monte_carlo_price(110, 100, 0, .05, .2, 0, "call", paths=100)
    assert expired.price == 10 and expired.standard_error == 0 and expired.z_score == 0
    frozen = monte_carlo_price(100, 90, 1, .05, 0, 0, "call", paths=100)
    assert frozen.price == pytest.approx(frozen.bsm_price, rel=1e-12) and frozen.standard_error == 0 and frozen.z_score == 0


@pytest.mark.parametrize("kwargs", [dict(paths=1), dict(paths=1001), dict(paths=2.5), dict(paths=True), dict(option_type="cal")])
def test_invalid_monte_carlo_inputs(kwargs):
    args = dict(S=100, K=100, T=1, r=.05, sigma=.2, q=0, option_type="call", paths=100)
    args.update(kwargs)
    with pytest.raises(ValueError):
        monte_carlo_price(**args)
