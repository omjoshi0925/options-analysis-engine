"""European options pricing and reproducible empirical diagnostics."""
from .core import BlackScholesEngine
from .numerics import numerical_greeks, greek_error_study
from .iv import IVResult, implied_volatility, solve_iv
from .american import BinomialResult, binomial_price, binomial_analysis, binomial_greeks, early_exercise_boundary
from .montecarlo import MonteCarloResult, monte_carlo_price
from .volatility import ESTIMATORS, VolatilityEstimate, realized_volatility

__version__ = "3.0.0"
__all__ = ["BlackScholesEngine", "numerical_greeks", "greek_error_study",
           "IVResult", "implied_volatility", "solve_iv",
           "BinomialResult", "binomial_price", "binomial_analysis", "binomial_greeks", "early_exercise_boundary",
           "MonteCarloResult", "monte_carlo_price",
           "ESTIMATORS", "VolatilityEstimate", "realized_volatility"]
