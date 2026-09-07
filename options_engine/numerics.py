"""Independent finite differences with valid symmetric stencils and step diagnostics."""
from dataclasses import replace
import numpy as np
import pandas as pd
from .core import BlackScholesEngine, option_kind


def numerical_greeks(S, K, T, r, sigma, q=0.0, h=1e-4, option_type="call", return_steps=False):
    """h is a relative step; actual parameter steps are returned on request.

    Central second-order differences. Steps near domain boundaries shrink
    symmetrically; no asymmetric clamp with a stale denominator is used.
    """
    option_kind(option_type)
    if not np.isfinite(h) or h <= 0:
        raise ValueError("h must be finite and positive")
    m = BlackScholesEngine(S, K, T, r, sigma, q)
    if T <= 0 or sigma <= 0:
        raise ValueError("Finite-difference Greeks require T > 0 and sigma > 0")
    steps = {"S": min(h*max(S, 1.0), S/4), "T": min(h*max(T, 1.0), T/4),
             "sigma": min(h*max(sigma, 1.0), sigma/4), "r": h*max(abs(r), 1.0)}
    differences = {}
    base = m.price(option_type)
    for key, step in steps.items():
        value = getattr(m, key)
        if value + step == value or value - step == value:
            raise ValueError(f"Step is below floating-point resolution for {key}")
        up = replace(m, **{key: value+step}).price(option_type)
        dn = replace(m, **{key: value-step}).price(option_type)
        differences[key] = (up-dn)/(2*step)
        if key == "S":
            gamma = (up-2*base+dn)/step**2
    result = dict(Delta=differences["S"], Gamma=gamma, Theta=-differences["T"],
                  Vega=differences["sigma"], Rho=differences["r"])
    return (result, steps) if return_steps else result


def greek_error_study(model, option_type="call", steps=None):
    steps = np.logspace(-2, -7, 11) if steps is None else steps
    analytic = model.analytical_greeks(option_type)
    parameter = dict(Delta="S", Gamma="S", Theta="T", Vega="sigma", Rho="r")
    rows = []
    for h in steps:
        result, used = numerical_greeks(model.S, model.K, model.T, model.r,
                                        model.sigma, model.q, float(h), option_type, True)
        for greek, expected in analytic.items():
            error = abs(result[greek]-expected)
            rows.append(dict(option_type=option_type, greek=greek, relative_step=h,
                             parameter_step=used[parameter[greek]], analytical=expected,
                             numerical=result[greek], absolute_error=error,
                             relative_error=error/abs(expected) if abs(expected) > 1e-10 else np.nan))
    return pd.DataFrame(rows)
