"""Auditable IV inversion; failures retain status instead of disappearing as NaN."""
from dataclasses import dataclass, replace
import math
from scipy.optimize import brentq
from .core import BlackScholesEngine, option_kind


@dataclass(frozen=True)
class IVResult:
    volatility: float = math.nan
    converged: bool = False
    status: str = "not_solved"
    method: str = "brent"
    iterations: int = 0
    residual: float = math.nan
    vega: float = math.nan
    poorly_identified: bool = False
    fallback_used: bool = False


def implied_volatility(price, S, K, T, r, q=0.0, option_type="call", method="brent",
                       initial=0.2, max_sigma=10.0, price_tol=1e-8, maxiter=100,
                       fallback=True):
    """Bracket [0,max_sigma], expand from 0.5. Newton stays inside the bracket.

    Price proximity to either bound means IV is poorly identified at price_tol;
    an upper-bound quote has no finite solution. A price residual gates success.
    """
    option_kind(option_type)
    if method not in ("brent", "newton"):
        raise ValueError("method must be 'brent' or 'newton'")
    if (not all(math.isfinite(x) and x > 0 for x in (initial, max_sigma, price_tol))
            or not isinstance(maxiter, int) or maxiter < 1):
        raise ValueError("Invalid solver configuration")
    try:
        model = BlackScholesEngine(S, K, T, r, 0.0, q)
        price = float(price)
    except (ValueError, TypeError, OverflowError):
        return IVResult(status="invalid_input", method=method)
    if not math.isfinite(price) or price < 0:
        return IVResult(status="invalid_price", method=method)
    if T == 0:
        return IVResult(status="expired_iv_undefined", method=method)
    low_price, high_price = model.bounds(option_type)
    if price < low_price-price_tol or price > high_price+price_tol:
        return IVResult(status="outside_european_bounds", method=method)
    if abs(price-low_price) <= price_tol:
        return IVResult(0.0, True, "lower_bound_limit", method, 0,
                        low_price-price, 0.0, True)
    if price >= high_price-price_tol:
        return IVResult(status="upper_bound_no_finite_iv", method=method, poorly_identified=True)

    def objective(vol):
        return replace(model, sigma=vol).price(option_type)-price

    lo, hi = 0.0, min(0.5, max_sigma)
    while objective(hi) < 0 and hi < max_sigma:
        hi = min(2*hi, max_sigma)
    if objective(hi) < 0:
        return IVResult(status="root_above_max_sigma", method=method)

    def finish(vol, count, used_fallback=False):
        residual = objective(vol)
        vega = replace(model, sigma=vol).analytical_greeks(option_type)["Vega"] if vol else 0.0
        valid = abs(residual) <= price_tol
        return IVResult(vol if valid else math.nan, valid,
                        "converged" if valid else "residual_too_large", method,
                        count, residual, vega, vega < 1e-6, used_fallback)

    newton_iterations = 0
    if method == "newton":
        vol = min(max(initial, lo+1e-12), hi-1e-12)
        for newton_iterations in range(1, maxiter+1):
            error = objective(vol)
            if abs(error) <= price_tol:
                return finish(vol, newton_iterations)
            if error > 0:
                hi = vol
            else:
                lo = vol
            vega = replace(model, sigma=vol).analytical_greeks(option_type)["Vega"]
            if vega < 1e-12:
                break
            candidate = vol-error/vega
            vol = candidate if lo < candidate < hi else (lo+hi)/2
        if not fallback:
            return IVResult(status="newton_nonconvergence", method=method,
                            iterations=newton_iterations)
    try:
        vol, result = brentq(objective, lo, hi, xtol=1e-13, rtol=1e-12,
                             maxiter=maxiter, full_output=True, disp=False)
    except (ValueError, RuntimeError):
        return IVResult(status="brent_failure", method=method, fallback_used=method == "newton")
    if not result.converged:
        return IVResult(status="max_iterations", method=method, iterations=maxiter,
                        fallback_used=method == "newton")
    # Endpoint roots can have implementation-specific iteration counts in SciPy.
    iterations = max(0, min(int(result.iterations), maxiter))
    return finish(vol, iterations+newton_iterations, method == "newton")


def solve_iv(P_market, S, K, T, r, q=0.0, opt_type="call", method="brent"):
    """Compatibility wrapper for the supplied prototype; use rich results for analysis."""
    return implied_volatility(P_market, S, K, T, r, q, opt_type, method).volatility
