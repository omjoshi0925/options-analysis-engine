from dataclasses import replace
import numpy as np
import pytest
from scipy.integrate import quad
from scipy.stats import norm
from options_engine import BlackScholesEngine, numerical_greeks


def test_reference_prices_and_greeks():
    m = BlackScholesEngine(100, 100, 1, .05, .2)
    assert m.price("call") == pytest.approx(10.450583572185565, abs=1e-11)
    assert m.price("put") == pytest.approx(5.573526022256971, abs=1e-11)
    expected = dict(Delta=.6368306511756191, Gamma=.018762017345846895,
                    Theta=-6.414027546438197, Vega=37.52403469169379, Rho=53.232481545376345)
    assert m.analytical_greeks() == pytest.approx(expected)


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("r,q", [(.04, .02), (-.03, .01), (.01, -.01)])
def test_independent_risk_neutral_quadrature(kind, r, q):
    m = BlackScholesEngine(105, 110, .7, r, .32, q)
    zstrike = (np.log(m.K/m.S)-(m.r-m.q-.5*m.sigma**2)*m.T)/(m.sigma*np.sqrt(m.T))
    def integrand(z):
        terminal = m.S*np.exp((m.r-m.q-.5*m.sigma**2)*m.T+m.sigma*np.sqrt(m.T)*z)
        payoff = max(terminal-m.K, 0) if kind == "call" else max(m.K-terminal, 0)
        return np.exp(-m.r*m.T)*payoff*norm.pdf(z)
    lo, hi = (zstrike, 12) if kind == "call" else (-12, zstrike)
    expectation = quad(integrand, lo, hi, epsabs=1e-10)[0]
    assert m.price(kind) == pytest.approx(expectation, abs=1e-9)


@pytest.mark.parametrize("S,K,T,r,sigma,q", [
    (100,100,1,.05,.2,0), (80,100,.3,-.02,.4,.03), (140,100,2,.07,.35,.05),
    (100,100,1/365,.04,.25,.01), (10,12,.5,.02,.8,0), (1000,1100,.75,.03,.3,.02)])
@pytest.mark.parametrize("kind", ["call", "put"])
def test_numerical_derivatives(S,K,T,r,sigma,q,kind):
    m = BlackScholesEngine(S,K,T,r,sigma,q)
    numeric = numerical_greeks(S,K,T,r,sigma,q,h=1e-5,option_type=kind)
    for key, expected in m.analytical_greeks(kind).items():
        assert numeric[key] == pytest.approx(expected, rel=4e-5, abs=3e-5), key


def test_parity_bounds_and_monotonicity_across_grid():
    for S in (20,80,100,120,500):
        for T in (1e-5,.01,1,5):
            m = BlackScholesEngine(S,100,T,-.02,.3,.03)
            assert m.verify_parity() < 1e-12
            for kind in ("call", "put"):
                lo, hi = m.bounds(kind)
                assert lo-1e-12 <= m.price(kind) <= hi+1e-12
                assert replace(m,sigma=.4).price(kind) >= m.price(kind)-1e-10


def test_small_otm_price_survives_cancellation():
    m = BlackScholesEngine(100,200,.25,.03,.20)
    assert 0 < m.price("call") < 1e-8


@pytest.mark.parametrize("kind", ["call", "put"])
def test_zero_time_and_zero_volatility(kind):
    m = BlackScholesEngine(90,100,0,.05,0,.02)
    assert m.price(kind) == (0 if kind == "call" else 10)
    m = replace(m,T=1)
    assert m.price(kind) == m.bounds(kind)[0]
    assert np.isnan(m.d1)
    with pytest.raises(ValueError):
        m.analytical_greeks(kind)


@pytest.mark.parametrize("key,value", [("S",0),("K",-1),("T",-1),("sigma",-1),("r",np.nan),("q",np.inf)])
def test_invalid_inputs(key,value):
    args = dict(S=100,K=100,T=1,r=.05,sigma=.2,q=0)
    args[key] = value
    with pytest.raises(ValueError):
        BlackScholesEngine(**args)


def test_invalid_option_type_and_market_units():
    m = BlackScholesEngine(100,100,1,.05,.2,.02)
    with pytest.raises(ValueError):
        m.price("CALLL")
    raw, scaled = m.analytical_greeks("put"), m.analytical_greeks("put","market")
    assert scaled["Theta"] == raw["Theta"]/365
    assert scaled["Vega"] == raw["Vega"]/100
    assert scaled["Rho"] == raw["Rho"]/100
    assert scaled["Delta"] == raw["Delta"] < 0


def test_boundary_stencils_are_symmetric_and_reported():
    _, steps = numerical_greeks(.01,.01,1e-6,.03,.0001,h=.01,return_steps=True)
    assert steps == pytest.approx(dict(S=.0025,T=2.5e-7,sigma=.000025,r=.01))
    with pytest.raises(ValueError):
        numerical_greeks(100,100,0,.03,.2)
