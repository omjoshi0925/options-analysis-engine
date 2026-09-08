"""Realized volatility estimators from daily bars for the independent baseline.

Every estimator is annualized with sqrt(periods_per_year) and reports the
estimator name, window, and bar count it used, so a baseline stays auditable.
Close-to-close is the historical default. The range-based estimators use the
day's high/low (and open) and have lower sampling variance for the same window,
but discrete trading biases them low, and only Yang-Zhang includes overnight
gaps. Bars must be in chronological order.
"""
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd

ESTIMATORS = ("close_to_close", "parkinson", "garman_klass", "rogers_satchell", "yang_zhang")
REQUIRED_COLUMNS = {"close_to_close": ("close",), "parkinson": ("high", "low"), "garman_klass": ("open", "high", "low", "close"),
                    "rogers_satchell": ("open", "high", "low", "close"), "yang_zhang": ("open", "high", "low", "close")}


@dataclass(frozen=True)
class VolatilityEstimate:
    sigma: float
    estimator: str
    window: int
    observations: int
    periods_per_year: int
    clamped_bars: int = 0


def _bars(frame, estimator):
    columns = {str(name).strip().lower().replace(" ", "_"): name for name in frame.columns}
    needed = REQUIRED_COLUMNS[estimator]
    if missing := [name for name in needed if name not in columns]:
        raise ValueError(f"{estimator} needs daily {missing} columns")
    bars = pd.DataFrame({name: pd.to_numeric(frame[columns[name]], errors="coerce").to_numpy(float) for name in needed}).dropna()
    return bars.reset_index(drop=True)


def _rogers_satchell_terms(bars):
    return (np.log(bars.high/bars.close)*np.log(bars.high/bars.open)+np.log(bars.low/bars.close)*np.log(bars.low/bars.open))


def realized_volatility(frame, estimator="close_to_close", window=60, periods_per_year=252):
    """Annualized volatility from the last `window` returns (close-to-close, Yang-Zhang) or bars (range estimators)."""
    if estimator not in ESTIMATORS:
        raise ValueError(f"estimator must be one of {ESTIMATORS}")
    if isinstance(window, bool) or not isinstance(window, (int, np.integer)) or window < 2:
        raise ValueError("window must be an integer >= 2")
    if isinstance(periods_per_year, bool) or not isinstance(periods_per_year, (int, np.integer)) or periods_per_year < 1:
        raise ValueError("periods_per_year must be a positive integer")
    bars = _bars(frame, estimator)
    needed = window+1 if estimator in ("close_to_close", "yang_zhang") else window
    if len(bars) < needed:
        raise ValueError(f"Need {needed} complete daily bars for {estimator}; have {len(bars)}")
    bars = bars.tail(needed).reset_index(drop=True)
    if (bars <= 0).any().any():
        raise ValueError("Nonpositive historical price")
    clamped = 0
    if "high" in bars:
        anchors = [c for c in ("open", "close") if c in bars]
        if anchors:
            # Reported highs/lows occasionally exclude the open or close; widen the range instead of taking a log of a negative ratio.
            top, bottom = bars[anchors].max(axis=1), bars[anchors].min(axis=1)
            clamped = int(((bars.high < top) | (bars.low > bottom)).sum())
            bars["high"], bars["low"] = np.maximum(bars.high, top), np.minimum(bars.low, bottom)
        if (bars.high < bars.low).any():
            raise ValueError("Daily high below daily low")
    if estimator == "close_to_close":
        variance = float(np.var(np.diff(np.log(bars.close.to_numpy())), ddof=1))
    elif estimator == "parkinson":
        variance = float(np.mean(np.log(bars.high/bars.low)**2)/(4*math.log(2)))
    elif estimator == "garman_klass":
        variance = float(np.mean(0.5*np.log(bars.high/bars.low)**2-(2*math.log(2)-1)*np.log(bars.close/bars.open)**2))
    elif estimator == "rogers_satchell":
        variance = float(np.mean(_rogers_satchell_terms(bars)))
    else:
        current, previous_close = bars.iloc[1:].reset_index(drop=True), bars.close.iloc[:-1].reset_index(drop=True)
        overnight = np.log(current.open/previous_close)
        open_to_close = np.log(current.close/current.open)
        n = len(current)
        k = 0.34/(1.34+(n+1)/(n-1))
        variance = float(np.var(overnight, ddof=1)+k*np.var(open_to_close, ddof=1)+(1-k)*np.mean(_rogers_satchell_terms(current)))
    sigma = math.sqrt(max(variance, 0.0)*periods_per_year)
    if not math.isfinite(sigma) or sigma <= 0:
        raise ValueError(f"Invalid realized volatility from {estimator}")
    return VolatilityEstimate(sigma, estimator, int(window), len(bars), int(periods_per_year), clamped)
