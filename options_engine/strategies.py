"""Multi-leg option positions: exact expiry payoff, breakevens, and closed-form value and Greeks.

Legs share one underlying and one expiry. Premiums default to the closed-form
price at construction, so profit figures are a theoretical mark, not executable
quotes. Payoffs are per share; no contract multiplier is applied.
"""
from dataclasses import dataclass, replace
import math
import numpy as np
from .core import BlackScholesEngine

LEG_KINDS = ("call", "put", "stock")


@dataclass(frozen=True)
class Leg:
    kind: str
    quantity: float
    strike: float | None = None
    premium: float | None = None

    def __post_init__(self):
        if self.kind not in LEG_KINDS:
            raise ValueError(f"kind must be one of {LEG_KINDS}")
        if not math.isfinite(self.quantity) or self.quantity == 0:
            raise ValueError("quantity must be a nonzero finite number; negative is short")
        if self.kind == "stock" and self.strike is not None:
            raise ValueError("stock legs have no strike")
        if self.kind != "stock" and (self.strike is None or not math.isfinite(self.strike) or self.strike <= 0):
            raise ValueError("option legs need a positive finite strike")
        if self.premium is not None and (not math.isfinite(self.premium) or self.premium < 0):
            raise ValueError("premium must be finite and nonnegative")

    def intrinsic(self, spot):
        spot = np.asarray(spot, float)
        if self.kind == "call":
            return np.maximum(spot-self.strike, 0.0)
        if self.kind == "put":
            return np.maximum(self.strike-spot, 0.0)
        return spot

    def model_price(self, S, T, r, sigma, q=0.0):
        return float(S) if self.kind == "stock" else BlackScholesEngine(S, self.strike, T, r, sigma, q).price(self.kind)


@dataclass(frozen=True)
class Strategy:
    name: str
    legs: tuple

    def __post_init__(self):
        object.__setattr__(self, "legs", tuple(self.legs))
        if not self.legs:
            raise ValueError("A strategy needs at least one leg")
        if any(leg.premium is None for leg in self.legs):
            raise ValueError("Every leg needs a premium; Strategy.priced fills missing premiums from the closed form")

    @classmethod
    def priced(cls, name, legs, S, T, r, sigma, q=0.0):
        """Fill missing premiums with the closed-form price; stock legs enter at S."""
        return cls(name, tuple(leg if leg.premium is not None else replace(leg, premium=leg.model_price(S, T, r, sigma, q)) for leg in legs))

    @property
    def net_premium(self):
        """Cash paid per share at inception; negative is a net credit."""
        return float(sum(leg.quantity*leg.premium for leg in self.legs))

    @property
    def strikes(self):
        return sorted({leg.strike for leg in self.legs if leg.strike is not None})

    def payoff(self, spot):
        """Profit per share at expiry, net of premiums, for scalar or array spot."""
        spot = np.asarray(spot, float)
        return sum(leg.quantity*(leg.intrinsic(spot)-leg.premium) for leg in self.legs)

    def value(self, S, T, r, sigma, q=0.0):
        """Theoretical profit per share before expiry: closed-form marks minus premiums."""
        return float(sum(leg.quantity*(leg.model_price(S, T, r, sigma, q)-leg.premium) for leg in self.legs))

    def greeks(self, S, T, r, sigma, q=0.0, units="raw"):
        total = dict(Delta=0.0, Gamma=0.0, Theta=0.0, Vega=0.0, Rho=0.0)
        for leg in self.legs:
            if leg.kind == "stock":
                total["Delta"] += leg.quantity
                continue
            for key, value in BlackScholesEngine(S, leg.strike, T, r, sigma, q).analytical_greeks(leg.kind, units).items():
                total[key] += leg.quantity*value
        return total

    @property
    def right_slope(self):
        """Payoff slope above the highest strike."""
        return float(sum(leg.quantity for leg in self.legs if leg.kind in ("call", "stock")))

    @property
    def left_slope(self):
        """Payoff slope below the lowest strike."""
        return float(sum(leg.quantity for leg in self.legs if leg.kind == "stock")-sum(leg.quantity for leg in self.legs if leg.kind == "put"))

    def breakevens(self):
        """Exact zero crossings of the expiry payoff; the payoff is linear between strikes and beyond them."""
        points = [0.0]+self.strikes
        values = self.payoff(points)
        roots = []
        for (x0, v0), (x1, v1) in zip(zip(points[:-1], values[:-1], strict=True), zip(points[1:], values[1:], strict=True), strict=True):
            if v0 == 0:
                roots.append(x0)
            elif v0*v1 < 0:
                roots.append(x0+(x1-x0)*v0/(v0-v1))
        last, slope = values[-1], self.right_slope
        if last == 0:
            roots.append(points[-1])
        elif slope != 0 and last*slope < 0:
            roots.append(points[-1]-last/slope)
        return sorted({round(float(root), 10) for root in roots if root > 0 or (root == 0 and self.payoff(0.0) == 0)})

    def summary(self, S=None, T=None, r=None, sigma=None, q=0.0):
        """Expiry structure (exact) plus the current mark and Greeks when pricing inputs are supplied."""
        values = self.payoff([0.0]+self.strikes)
        slope = self.right_slope
        result = dict(name=self.name, legs=[dict(kind=leg.kind, quantity=leg.quantity, strike=leg.strike, premium=leg.premium) for leg in self.legs],
                      net_premium=self.net_premium, strikes=self.strikes, breakevens=self.breakevens(),
                      max_profit=math.inf if slope > 0 else float(values.max()),
                      max_loss=-math.inf if slope < 0 else float(values.min()),
                      unbounded_profit=slope > 0, unbounded_loss=slope < 0, right_slope=slope, left_slope=self.left_slope)
        if S is not None:
            result.update(spot=float(S), current_value=self.value(S, T, r, sigma, q),
                          greeks=self.greeks(S, T, r, sigma, q, "market"))
        return result


def _width(S, width):
    if width is None:
        width = 0.05*S
    if not math.isfinite(width) or width <= 0:
        raise ValueError("width must be positive")
    return float(width)


PRESETS = {
    "long_call": lambda K, w: [Leg("call", 1, K)],
    "long_put": lambda K, w: [Leg("put", 1, K)],
    "short_call": lambda K, w: [Leg("call", -1, K)],
    "short_put": lambda K, w: [Leg("put", -1, K)],
    "covered_call": lambda K, w: [Leg("stock", 1), Leg("call", -1, K+w)],
    "protective_put": lambda K, w: [Leg("stock", 1), Leg("put", 1, K-w)],
    "collar": lambda K, w: [Leg("stock", 1), Leg("put", 1, K-w), Leg("call", -1, K+w)],
    "bull_call_spread": lambda K, w: [Leg("call", 1, K), Leg("call", -1, K+w)],
    "bear_put_spread": lambda K, w: [Leg("put", 1, K), Leg("put", -1, K-w)],
    "long_straddle": lambda K, w: [Leg("call", 1, K), Leg("put", 1, K)],
    "short_straddle": lambda K, w: [Leg("call", -1, K), Leg("put", -1, K)],
    "long_strangle": lambda K, w: [Leg("call", 1, K+w), Leg("put", 1, K-w)],
    "iron_condor": lambda K, w: [Leg("put", 1, K-2*w), Leg("put", -1, K-w), Leg("call", -1, K+w), Leg("call", 1, K+2*w)],
    "long_call_butterfly": lambda K, w: [Leg("call", 1, K-w), Leg("call", -2, K), Leg("call", 1, K+w)],
}


def preset(name, S, T, r, sigma, q=0.0, strike=None, width=None):
    """Build a named strategy struck at `strike` (default: the spot) with wing `width` (default: 5% of spot)."""
    if name not in PRESETS:
        raise ValueError(f"Unknown preset; choose from {sorted(PRESETS)}")
    K = float(S if strike is None else strike)
    if not math.isfinite(K) or K <= 0:
        raise ValueError("strike must be positive")
    w = _width(float(S), width)
    if K-2*w <= 0:
        raise ValueError("width is too large for the strike; lower wings would be nonpositive")
    return Strategy.priced(name, PRESETS[name](K, w), S, T, r, sigma, q)
