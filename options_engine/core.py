"""Scalar Black-Scholes-Merton formulas; annual decimal rates, per-share prices."""
from dataclasses import dataclass
import math
from scipy.special import ndtr, log_ndtr


def option_kind(value):
    if value not in ("call", "put"):
        raise ValueError("option_type must be 'call' or 'put'")
    return value


@dataclass(frozen=True)
class BlackScholesEngine:
    S: float
    K: float
    T: float
    r: float
    sigma: float
    q: float = 0.0

    def __post_init__(self):
        for key in ("S", "K", "T", "r", "sigma", "q"):
            value = float(getattr(self, key))
            if not math.isfinite(value):
                raise ValueError(f"{key} must be finite")
            object.__setattr__(self, key, value)
        if self.S <= 0 or self.K <= 0:
            raise ValueError("S and K must be strictly positive")
        if self.T < 0 or self.sigma < 0:
            raise ValueError("T and sigma must be nonnegative; expired quotes are excluded upstream")
        try:
            if not all(math.isfinite(x) and x > 0 for x in (self.adjusted_spot, self.discounted_strike)):
                raise ValueError("Discounted amounts are outside floating-point range")
        except OverflowError as exc:
            raise ValueError("Discounted amounts are outside floating-point range") from exc

    @property
    def adjusted_spot(self):
        return self.S * math.exp(-self.q * self.T)

    @property
    def discounted_strike(self):
        return self.K * math.exp(-self.r * self.T)

    @property
    def d1(self):
        if self.T == 0 or self.sigma == 0:
            return math.nan  # Formula is undefined; price has an exact limiting branch.
        return (math.log(self.S) - math.log(self.K) +
                (self.r - self.q + 0.5 * self.sigma**2) * self.T) / (self.sigma * math.sqrt(self.T))

    @property
    def d2(self):
        return self.d1 - self.sigma * math.sqrt(self.T)

    def bounds(self, option_type="call"):
        option_kind(option_type)
        a, b = self.adjusted_spot, self.discounted_strike
        return (max(a-b, 0.0), a) if option_type == "call" else (max(b-a, 0.0), b)

    def price(self, option_type="call"):
        option_kind(option_type)
        if self.T == 0:
            return max(self.S-self.K, 0.0) if option_type == "call" else max(self.K-self.S, 0.0)
        a, b = self.adjusted_spot, self.discounted_strike
        if self.sigma == 0:
            return self.bounds(option_type)[0]
        # Price the OTM side in log space, then recover the ITM side by parity.
        # exp(x)-exp(y) = exp(x)*[-expm1(y-x)] reduces tail cancellation.
        if a <= b:
            x = math.log(a) + float(log_ndtr(self.d1))
            y = math.log(b) + float(log_ndtr(self.d2))
            call = math.exp(x) * -math.expm1(min(y-x, 0.0))
            return call if option_type == "call" else call + b-a
        x = math.log(b) + float(log_ndtr(-self.d2))
        y = math.log(a) + float(log_ndtr(-self.d1))
        put = math.exp(x) * -math.expm1(min(y-x, 0.0))
        return put if option_type == "put" else put + a-b

    def verify_parity(self):
        return abs((self.price("call")-self.price("put")) -
                   (self.adjusted_spot-self.discounted_strike))

    def analytical_greeks(self, option_type="call", units="raw"):
        """Theta=-dV/dT per year; Vega=dV/dsigma; Rho=dV/dr.

        market units: Theta/calendar day, Vega and Rho per +1 percentage point.
        Boundary Greeks are deliberately undefined: do not report clamped derivatives.
        """
        option_kind(option_type)
        if units not in ("raw", "market"):
            raise ValueError("units must be 'raw' or 'market'")
        if self.T == 0 or self.sigma == 0:
            raise ValueError("Greek diagnostics require T > 0 and sigma > 0")
        dq, dr = math.exp(-self.q*self.T), math.exp(-self.r*self.T)
        density = math.exp(-0.5*self.d1**2)/math.sqrt(2*math.pi)
        root_t = math.sqrt(self.T)
        gamma = dq*density/(self.S*self.sigma*root_t)
        vega = self.S*dq*density*root_t
        common_theta = -self.S*dq*density*self.sigma/(2*root_t)
        if option_type == "call":
            delta = dq*ndtr(self.d1)
            theta = common_theta - self.r*self.K*dr*ndtr(self.d2) + self.q*self.S*dq*ndtr(self.d1)
            rho = self.K*self.T*dr*ndtr(self.d2)
        else:
            delta = -dq*ndtr(-self.d1)
            theta = common_theta + self.r*self.K*dr*ndtr(-self.d2) - self.q*self.S*dq*ndtr(-self.d1)
            rho = -self.K*self.T*dr*ndtr(-self.d2)
        if units == "market":
            theta, vega, rho = theta/365.0, vega/100.0, rho/100.0
        return dict(Delta=float(delta), Gamma=float(gamma), Theta=float(theta),
                    Vega=float(vega), Rho=float(rho))
