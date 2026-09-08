"""Cox-Ross-Rubinstein binomial pricing for American and European exercise.

US equity and ETF options permit early exercise, while the closed form in
core.py is European. Pricing both exercise styles on one recombining tree with
the same S, K, T, r, sigma, q isolates the early-exercise premium: the common
discretization error largely cancels in the difference, and the European tree
value converges to the closed form as the step count grows.
"""
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd
from .core import BlackScholesEngine, option_kind


@dataclass(frozen=True)
class BinomialResult:
    price: float
    european_tree_price: float
    bsm_price: float
    early_exercise_premium: float
    discretization_error: float
    steps: int


@dataclass(frozen=True)
class _Tree:
    model: BlackScholesEngine
    steps: int
    dt: float
    probability: float
    discount: float

    def nodes(self, n):
        return self.model.S*np.exp(self.model.sigma*math.sqrt(self.dt)*(2*np.arange(n+1)-n))

    def intrinsic(self, n, option_type):
        nodes = self.nodes(n)
        return nodes-self.model.K if option_type == "call" else self.model.K-nodes

    def induct(self, option_type, american, keep=0, boundary=None):
        """Backward induction; returns the value vectors for steps 0..keep.

        With a boundary dict, records per step the largest (put) or smallest
        (call) node where immediate exercise strictly beats continuation.
        """
        values = np.maximum(self.intrinsic(self.steps, option_type), 0.0)
        kept = {}
        for n in range(self.steps-1, -1, -1):
            values = self.discount*(self.probability*values[1:]+(1-self.probability)*values[:-1])
            if american:
                intrinsic = self.intrinsic(n, option_type)
                if boundary is not None:
                    chosen = self.nodes(n)[intrinsic > values]
                    boundary[n] = float(chosen.max() if option_type == "put" else chosen.min()) if len(chosen) else math.nan
                values = np.maximum(values, intrinsic)
            if n <= keep:
                kept[n] = values.copy()
        return kept


def _tree(S, K, T, r, sigma, q, steps):
    model = BlackScholesEngine(S, K, T, r, sigma, q)
    if isinstance(steps, bool) or not isinstance(steps, (int, np.integer)) or steps < 1:
        raise ValueError("steps must be a positive integer")
    if model.T <= 0 or model.sigma <= 0:
        raise ValueError("Binomial pricing requires T > 0 and sigma > 0; BlackScholesEngine gives the exact limiting price")
    dt = model.T/int(steps)
    up = math.exp(model.sigma*math.sqrt(dt))
    down = 1/up
    probability = (math.exp((model.r-model.q)*dt)-down)/(up-down)
    if not 0 < probability < 1:
        raise ValueError("Risk-neutral step probability is outside (0, 1); increase steps so |r-q|*sqrt(dt) < sigma")
    return _Tree(model, int(steps), dt, probability, math.exp(-model.r*dt))


def binomial_price(S, K, T, r, sigma, q=0.0, option_type="call", steps=200, american=True):
    """CRR tree price per share. steps is the number of time steps."""
    option_kind(option_type)
    return float(_tree(S, K, T, r, sigma, q, steps).induct(option_type, american)[0][0])


def binomial_analysis(S, K, T, r, sigma, q=0.0, option_type="call", steps=200):
    """American and European prices on the same tree plus the closed-form reference."""
    option_kind(option_type)
    tree = _tree(S, K, T, r, sigma, q, steps)
    american = float(tree.induct(option_type, True)[0][0])
    european = float(tree.induct(option_type, False)[0][0])
    bsm = tree.model.price(option_type)
    # Monotone induction makes American >= European at every node; the clamp removes rounding noise only.
    return BinomialResult(american, european, bsm, max(american-european, 0.0), european-bsm, tree.steps)


def early_exercise_boundary(S, K, T, r, sigma, q=0.0, option_type="put", steps=200):
    """Per step, the largest (put) or smallest (call) node where exercise beats continuation; NaN when none."""
    option_kind(option_type)
    tree = _tree(S, K, T, r, sigma, q, steps)
    boundary = {}
    tree.induct(option_type, True, boundary=boundary)
    return pd.DataFrame([dict(step=n, time_years=n*tree.dt, critical_spot=boundary.get(n, math.nan)) for n in range(tree.steps)])


def binomial_greeks(S, K, T, r, sigma, q=0.0, option_type="call", steps=200, american=True, units="raw"):
    """Delta, Gamma, and Theta from the first tree nodes; Vega and Rho by symmetric bumps on the same tree.

    Conventions match analytical_greeks: Theta = -dV/dT per year, Vega and Rho per unit
    decimal change; market units divide Theta by 365 and Vega/Rho by 100.
    """
    option_kind(option_type)
    if units not in ("raw", "market"):
        raise ValueError("units must be 'raw' or 'market'")
    tree = _tree(S, K, T, r, sigma, q, steps)
    if tree.steps < 2:
        raise ValueError("Tree Greeks need at least two steps")
    kept = tree.induct(option_type, american, keep=2)
    s1, s2 = tree.nodes(1), tree.nodes(2)
    v0, v1, v2 = kept[0][0], kept[1], kept[2]
    delta = (v1[1]-v1[0])/(s1[1]-s1[0])
    gamma = ((v2[2]-v2[1])/(s2[2]-s2[1])-(v2[1]-v2[0])/(s2[1]-s2[0]))/(0.5*(s2[2]-s2[0]))
    theta = (v2[1]-v0)/(2*tree.dt)

    def reprice(**changes):
        args = dict(S=S, K=K, T=T, r=r, sigma=sigma, q=q)
        args.update(changes)
        return binomial_price(args["S"], args["K"], args["T"], args["r"], args["sigma"], args["q"], option_type, steps, american)

    dsigma, dr = min(0.005, tree.model.sigma/4), 1e-4
    vega = (reprice(sigma=tree.model.sigma+dsigma)-reprice(sigma=tree.model.sigma-dsigma))/(2*dsigma)
    rho = (reprice(r=tree.model.r+dr)-reprice(r=tree.model.r-dr))/(2*dr)
    if units == "market":
        theta, vega, rho = theta/365.0, vega/100.0, rho/100.0
    return dict(Delta=float(delta), Gamma=float(gamma), Theta=float(theta), Vega=float(vega), Rho=float(rho))
