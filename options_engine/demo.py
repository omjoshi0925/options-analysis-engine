"""Deterministic synthetic chain with declared skew; never a market-data fallback."""
import numpy as np
import pandas as pd
from .core import BlackScholesEngine
from .data import time_to_expiry


def synthetic_snapshot():
    rng = np.random.default_rng(20260907)
    as_of = "2026-09-08T19:00:00Z"
    records = []
    for symbol, spot, base in (("DEMO_A", 100.0, .20), ("DEMO_B", 175.0, .28)):
        for expiry in ("2026-09-18", "2026-10-16", "2026-12-18"):
            T = time_to_expiry(expiry, as_of)
            for strike in np.linspace(.8*spot, 1.2*spot, 17):
                moneyness = np.log(spot/strike)
                sigma = base + .30*moneyness + .8*moneyness**2 + .025*np.sqrt(T)
                for kind in ("call", "put"):
                    mid = BlackScholesEngine(spot, strike, T, .04, sigma, .01).price(kind)
                    half = max(.005, .02*mid)
                    records.append(dict(symbol=symbol, contractSymbol=f"{symbol}_{expiry}_{kind}_{strike:.3f}",
                                        option_type=kind, expiration=expiry, as_of=as_of, spot=spot, strike=strike,
                                        bid=max(mid-half, 0), ask=mid+half, lastPrice=mid,
                                        volume=int(rng.integers(0, 2500)), openInterest=int(rng.integers(30, 6000)),
                                        impliedVolatility=sigma, r=.04, q=.01, baseline_sigma=base,
                                        baseline_source="declared_synthetic_constant", exercise_style="european",
                                        lastTradeDate=as_of, data_kind="synthetic", spot_source="synthetic",
                                        spot_timestamp=as_of, expiry_hour=16, generating_sigma=sigma))
    # Deliberate invalid records exercise audit paths; unique strikes avoid duplicates.
    for i, override in enumerate((dict(bid=0.0), dict(bid=5.0, ask=4.0), dict(volume=-1),
                                  dict(expiration="2020-01-17"), dict(ask=100.0))):
        row = records[20].copy()
        row.update(strike=60+i, contractSymbol=f"BAD_{i}")
        row.update(override)
        records.append(row)
    return pd.DataFrame(records), dict(data_kind="synthetic", provider="deterministic generator, seed 20260907",
                                       as_of=as_of, notes=["No observed market quotes. Deliberate skew and invalid quotes."], failures=[])
