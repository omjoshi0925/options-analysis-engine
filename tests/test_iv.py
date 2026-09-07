import numpy as np
import pytest
from options_engine import BlackScholesEngine, implied_volatility, solve_iv


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("method", ["brent", "newton"])
@pytest.mark.parametrize("S,K,T,sigma", [(100,100,1,.2),(80,100,.8,.5),(150,100,2,.35),
                                        (100,100,1/365,.3),(100,100,.25,3.0)])
def test_iv_round_trip(kind, method, S,K,T,sigma):
    price = BlackScholesEngine(S,K,T,-.01,sigma,.02).price(kind)
    result = implied_volatility(price,S,K,T,-.01,.02,kind,method)
    assert result.converged
    assert result.volatility == pytest.approx(sigma, abs=2e-8)
    assert abs(result.residual) <= 1e-8


def test_bounds_expiry_and_invalid_prices():
    args = (100,100,1,.05)
    lower = BlackScholesEngine(100,100,1,.05,0).price()
    assert implied_volatility(lower,*args).status == "lower_bound_limit"
    assert implied_volatility(lower,*args).poorly_identified
    assert implied_volatility(lower-1,*args).status == "outside_european_bounds"
    assert implied_volatility(100,*args).status == "upper_bound_no_finite_iv"
    assert implied_volatility(101,*args).status == "outside_european_bounds"
    for value in (np.nan,np.inf,-1):
        assert implied_volatility(value,*args).status == "invalid_price"
    assert implied_volatility(0,100,100,0,.05).status == "expired_iv_undefined"
    assert implied_volatility(1,0,100,1,.05).status == "invalid_input"


def test_newton_fallback_and_no_fallback_status():
    price = BlackScholesEngine(100,120,.2,.01,.5).price()
    failed = implied_volatility(price,100,120,.2,.01,method="newton",initial=.00001,fallback=False)
    assert not failed.converged and failed.status == "newton_nonconvergence"
    solved = implied_volatility(price,100,120,.2,.01,method="newton",initial=.00001)
    assert solved.fallback_used and solved.converged
    assert solved.volatility == pytest.approx(.5,abs=1e-8)


def test_max_sigma_and_iteration_failure():
    price = BlackScholesEngine(100,100,1,.05,.8).price()
    assert implied_volatility(price,100,100,1,.05,max_sigma=.5).status == "root_above_max_sigma"
    assert not implied_volatility(price,100,100,1,.05,maxiter=1).converged
    with pytest.raises(ValueError):
        implied_volatility(price,100,100,1,.05,method="typo")
    assert solve_iv(price,100,100,1,.05) == pytest.approx(.8,abs=1e-8)
