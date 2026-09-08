"""Monte Carlo pricing under the same lognormal dynamics; a third independent check.

Terminal-value simulation only: European payoffs without path dependence. The
standard error is reported with the estimate, so agreement with the closed form
is a z-score rather than a visual impression.
"""
from dataclasses import dataclass
import math
import numpy as np
from .core import BlackScholesEngine, option_kind


@dataclass(frozen=True)
class MonteCarloResult:
    price: float
    standard_error: float
    bsm_price: float
    z_score: float
    paths: int
    antithetic: bool
    seed: int | None


def monte_carlo_price(S, K, T, r, sigma, q=0.0, option_type="call", paths=200_000, seed=20260907, antithetic=True):
    """Discounted mean payoff over simulated terminal prices; antithetic pairs halve the draws."""
    option_kind(option_type)
    model = BlackScholesEngine(S, K, T, r, sigma, q)
    if isinstance(paths, bool) or not isinstance(paths, (int, np.integer)) or paths < 2:
        raise ValueError("paths must be an integer >= 2")
    if antithetic and paths % 2:
        raise ValueError("Antithetic sampling needs an even number of paths")
    rng = np.random.default_rng(seed)
    draws = rng.standard_normal(paths//2 if antithetic else paths)
    z = np.concatenate([draws, -draws]) if antithetic else draws
    terminal = model.S*np.exp((model.r-model.q-0.5*model.sigma**2)*model.T+model.sigma*math.sqrt(model.T)*z)
    payoff = np.maximum(terminal-model.K, 0.0) if option_type == "call" else np.maximum(model.K-terminal, 0.0)
    discounted = math.exp(-model.r*model.T)*payoff
    samples = 0.5*(discounted[:paths//2]+discounted[paths//2:]) if antithetic else discounted
    price = float(samples.mean())
    error = float(samples.std(ddof=1)/math.sqrt(len(samples)))
    if error <= 1e-12*max(1.0, abs(price)):
        error = 0.0  # Rounding noise from a deterministic (zero-variance) simulation, not sampling error.
    bsm = model.price(option_type)
    z_score = (price-bsm)/error if error > 0 else 0.0
    return MonteCarloResult(price, error, bsm, float(z_score), int(paths), bool(antithetic), seed)
